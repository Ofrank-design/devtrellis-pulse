"""Command line interface. Exit codes are listed in docs/reference/exit-codes.md."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from pathlib import Path
from typing import Any

from devtrellis_pulse import __version__
from devtrellis_pulse.app import inspect_service, report_service, run_service
from devtrellis_pulse.app.commands import COMMANDS
from devtrellis_pulse.app.services import (
    Environment,
    resolve_config_path,
    resolve_environment,
)
from devtrellis_pulse.core import errors as E
from devtrellis_pulse.core.config import load_config, starter_yaml
from devtrellis_pulse.core.logging import configure as configure_logging
from devtrellis_pulse.discovery.planner import build_plan
from devtrellis_pulse.ledger import reader
from devtrellis_pulse.ledger.retention import apply_retention
from devtrellis_pulse.platform.paths import default_state_dir, is_writable_dir
from devtrellis_pulse.policy.engine import PolicyEngine
from devtrellis_pulse.repository.git_cli import GitCli
from devtrellis_pulse.scheduling import schedule as sched
from devtrellis_pulse.scheduling.lock import RunLock
from devtrellis_pulse.tasks import CONFIGURABLE, REGISTRY

_SUMMARY = {c.name: c.summary for c in COMMANDS}
_LABELS = {
    "passed": ("PASS", "32"),
    "no_changes": ("PASS", "32"),
    "planned": ("PLAN", "36"),
    "partial_success": ("WARN", "33"),
    "failed": ("FAIL", "31"),
    "timed_out": ("FAIL", "31"),
    "blocked": ("BLOCKED", "31"),
    "skipped": ("SKIP", "90"),
    "cancelled": ("SKIP", "90"),
    "warning": ("WARN", "33"),
    "info": ("INFO", "36"),
    "ok": ("OK", "32"),
}


class Printer:
    def __init__(self, quiet: bool, color: bool, as_json: bool) -> None:
        self.quiet, self.color, self.as_json = quiet, color, as_json

    def label(self, status: str) -> str:
        text, code = _LABELS.get(status, (status.upper(), "0"))
        text = f"[{text}]"
        return f"\033[{code}m{text}\033[0m" if self.color else text

    def info(self, text: str = "") -> None:
        if not self.quiet:
            print(text)

    def always(self, text: str) -> None:
        print(text)

    def json(self, data: Any) -> None:
        print(json.dumps(data, indent=2, default=str))


def _common() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(add_help=False, argument_default=argparse.SUPPRESS)
    p.add_argument("--config", metavar="PATH", help="configuration file (default: pulse.yml)")
    p.add_argument("--repo", metavar="PATH", help="repository root (overrides the config file)")
    p.add_argument("--state-dir", metavar="PATH", help="local state directory")
    p.add_argument("--json", action="store_true", help="machine readable output")
    p.add_argument("-v", "--verbose", action="store_true", help="diagnostic detail on stderr")
    p.add_argument("-q", "--quiet", action="store_true", help="only errors and requested output")
    p.add_argument("--no-color", action="store_true", help="disable ANSI colors")
    return p


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pulse",
        description="Local first repository maintenance. Checks, reports and verified commits.",
        parents=[_common()],
        epilog="Start with: pulse init, then pulse plan, then pulse run --execute",
    )
    parser.add_argument("--version", action="version", version=f"pulse {__version__}")
    sub = parser.add_subparsers(dest="command", required=True, metavar="COMMAND")

    def add(name: str) -> argparse.ArgumentParser:
        return sub.add_parser(name, parents=[_common()], help=_SUMMARY[name], description=_SUMMARY[name])

    add("init").add_argument("--force", action="store_true", help="overwrite an existing file")
    add("inspect")
    p = add("plan")
    p.add_argument("--task", action="append", metavar="ID", help="limit to a task (repeatable)")
    p.add_argument("--dry-run", action="store_true", help="accepted for clarity; plan never executes")
    p = add("run")
    p.add_argument("--task", action="append", metavar="ID", help="limit to a task (repeatable)")
    group = p.add_mutually_exclusive_group()
    group.add_argument("--dry-run", action="store_true", help="plan only")
    group.add_argument("--execute", action="store_true", help="run for real")
    p.add_argument("--scheduled", action="store_true", help="invoked by a scheduler")
    p = add("report")
    p.add_argument("--latest", action="store_true", help="the most recent run (default)")
    p.add_argument("--run-id", metavar="ID", help="a specific run")
    p.add_argument("--format", choices=("markdown", "json"), default="markdown")
    p.add_argument("--output", metavar="PATH", help="write the report to a file")
    p = add("history")
    p.add_argument("--limit", type=int, default=10, help="how many runs to show (1 to 100)")
    add("tasks")
    p = add("schedule")
    p.add_argument("--at", default="18:00", metavar="HH:MM", help="local time of day")
    p.add_argument(
        "--for", dest="target", choices=("cron", "systemd", "github", "windows", "all"), default="all"
    )
    p = add("ledger")
    p.add_argument("action", choices=("check", "prune"))
    p.add_argument("--yes", action="store_true", help="confirm a destructive prune")
    add("validate-config")
    add("doctor")
    add("version")
    return parser


# ---- helpers --------------------------------------------------------------------------------


def _opt(args: argparse.Namespace, name: str, default: Any = None) -> Any:
    return getattr(args, name, default)


def _printer(args: argparse.Namespace) -> Printer:
    no_color = _opt(args, "no_color", False) or "NO_COLOR" in os.environ
    color = sys.stdout.isatty() and not no_color
    return Printer(_opt(args, "quiet", False), color, _opt(args, "json", False))


def _env(args: argparse.Namespace) -> Environment:
    return resolve_environment(_opt(args, "config"), _opt(args, "repo"), _opt(args, "state_dir"))


def _print_plan(out: Printer, plan: list) -> None:
    rows = [f"{'TASK':<22}{'STATUS':<9}{'OPS':>4}  {'EST':>6}  REASON"]
    for p in plan:
        est = f"{p.estimated_seconds}s" if p.estimated_seconds is not None else "-"
        rows.append(f"{p.task_id:<22}{p.status:<9}{p.operations:>4}  {est:>6}  {p.reason}")
    out.info("\n".join(rows))


def _print_run(out: Printer, run: Any) -> None:
    out.info(f"{out.label(run.status)} run {run.run_id}: {run.status}")
    for task in run.tasks:
        out.info(f"  {out.label(task.status)} {task.task_id}: {task.summary}")
    for warning in run.warnings:
        out.info(f"  {out.label('warning')} {warning}")
    out.info(f"  commit: {run.commit_status}")
    for record in run.commits:
        if record.status == "committed":
            out.info(f"    {record.sha[:12]} {record.subject}" + (" (pushed)" if record.pushed else ""))
        elif record.reason:
            out.info(f"    {record.status}: {record.reason}")
    for path in run.reports:
        out.info(f"  report: {path}")
    for action in run.operator_actions:
        out.info(f"  next: {action}")


# ---- commands -------------------------------------------------------------------------------


def cmd_init(args: argparse.Namespace, out: Printer) -> int:
    path = Path(_opt(args, "config") or "pulse.yml")
    if path.exists() and not args.force:
        raise E.ConfigError(f"{path} already exists (use --force to overwrite it)")
    path.write_text(starter_yaml(), encoding="utf-8")
    out.info(f"wrote {path}")
    out.info("Next: pulse validate-config, then pulse plan")
    return 0


def cmd_inspect(args: argparse.Namespace, out: Printer) -> int:
    env = _env(args)
    data = inspect_service.inspect(env.repo)
    if out.as_json:
        out.json(data)
        return 0
    state = "clean" if data["clean"] else (
        f"{len(data['staged'])} staged, {len(data['modified'])} modified, "
        f"{len(data['untracked'])} untracked"
    )
    out.always(
        "\n".join(
            [
                f"root:     {data['root']}",
                f"branch:   {data['branch'] or 'detached HEAD'}",
                f"head:     {data['head'] or 'no commits yet'}",
                f"remote:   {data['remote'] or 'none'}",
                f"state:    {state}",
                f"git:      {data['git_version']}",
            ]
            + ([f"in progress: {data['operation_in_progress']}"] if data["operation_in_progress"] else [])
            + (["note:     shallow clone"] if data["shallow"] else [])
            + (["note:     sparse checkout"] if data["sparse"] else [])
            + ([f"note:     {len(data['submodules'])} submodule(s) not inspected"] if data["submodules"] else [])
        )
    )
    return 0


def cmd_plan(args: argparse.Namespace, out: Printer) -> int:
    env = _env(args)
    run = run_service.run(env, dry_run=True, only=_opt(args, "task"))
    if out.as_json:
        out.json(run.to_dict())
    else:
        _print_plan(out, run.plan)
        for warning in run.warnings:
            out.info(f"{out.label('warning')} {warning}")
        out.info("\nThis is a plan. Nothing was executed or changed.")
    return run.exit_code


def cmd_run(args: argparse.Namespace, out: Printer) -> int:
    env = _env(args)
    if args.dry_run:
        dry = True
    elif args.execute:
        dry = False
    else:
        dry = bool(env.cfg["runtime"]["dry_run_by_default"])
        if dry:
            out.info("runtime.dry_run_by_default is true, so this is a dry run. Add --execute to run.\n")
    if not dry and not out.quiet:
        risky = [
            t for t in CONFIGURABLE
            if env.cfg["tasks"][t]["enabled"] and REGISTRY[t].requires_subprocess
        ]
        if risky:
            print(
                f"warning: {', '.join(risky)} will execute code from this repository. "
                "Only continue for repositories you trust.",
                file=sys.stderr,
            )
    run = run_service.run(
        env, dry_run=dry, only=_opt(args, "task"), scheduled=_opt(args, "scheduled", False)
    )
    if out.as_json:
        out.json(run.to_dict())
    elif dry:
        _print_plan(out, run.plan)
        for warning in run.warnings:
            out.info(f"{out.label('warning')} {warning}")
        out.info("\nDry run: nothing was executed or changed.")
    elif run.status == "skipped":
        for warning in run.warnings:
            out.info(f"{out.label('skipped')} {warning}")
    else:
        _print_run(out, run)
    return run.exit_code


def cmd_report(args: argparse.Namespace, out: Printer) -> int:
    env = _env(args)
    run = report_service.load_run(env, _opt(args, "run_id"))
    text = report_service.render(env, run, args.format)
    if args.output:
        target = report_service.write_output(env, text, args.output)
        out.info(f"wrote {target}")
    else:
        out.always(text.rstrip("\n"))
    return 0


def cmd_history(args: argparse.Namespace, out: Printer) -> int:
    if not 1 <= args.limit <= 100:
        raise E.UsageError("--limit must be between 1 and 100")
    env = _env(args)
    runs = reader.recent_runs(env.ledger_path, env.fingerprint, args.limit)
    rows = [
        {
            "run_id": r["run_id"],
            "status": r["status"],
            "exit_code": r.get("exit_code"),
            "commit": r["run"].get("commit_status"),
            "finished": r["timestamp"],
        }
        for r in runs
    ]
    bad = reader.corrupt_lines(env.ledger_path)
    if out.as_json:
        out.json({"runs": rows, "corrupt_ledger_lines": bad})
        return 0
    if rows:
        out.always(f"{'RUN':<30}{'STATUS':<17}{'COMMIT':<11}FINISHED")
        for r in rows:
            out.always(f"{r['run_id']:<30}{r['status']:<17}{str(r['commit']):<11}{r['finished']}")
    else:
        out.always("no recorded runs yet")
    if bad:
        out.info(f"{out.label('warning')} {len(bad)} malformed ledger line(s): {bad[:10]}")
    return 0


def cmd_tasks(args: argparse.Namespace, out: Printer) -> int:
    data = [
        {
            "task_id": t.task_id,
            "name": t.name,
            "description": t.description,
            "enabled_by_default": t.enabled_by_default,
            "runs_subprocesses": t.requires_subprocess,
            "retry_safe": t.retry_safe,
            "idempotent": t.idempotent,
        }
        for t in REGISTRY.values()
    ]
    if out.as_json:
        out.json(data)
        return 0
    for t in data:
        flags = "runs repository code" if t["runs_subprocesses"] else "read only checks"
        out.always(f"{t['task_id']:<22}{t['name']:<32}{flags}")
    return 0


def cmd_schedule(args: argparse.Namespace, out: Printer) -> int:
    env = _env(args)
    cfg = env.cfg
    command = f"pulse run --scheduled --execute --config {env.config_path.resolve()}"
    if not cfg["schedule"]["enabled"]:
        out.info("note: schedule.enabled is false; these snippets show what it would look like.\n")
    out.info(f"Weekdays: {', '.join(cfg['schedule']['weekdays'])} ({cfg['schedule']['timezone']})")
    out.info("Next occurrences:")
    for moment in sched.next_occurrences(cfg, 3, args.at):
        out.info(f"  {moment:%a %Y-%m-%d %H:%M %Z}")
    pieces = {
        "cron": lambda: sched.render_cron(cfg, args.at, command),
        "systemd": lambda: sched.render_systemd(cfg, args.at, command),
        "github": lambda: sched.render_github_cron(cfg, args.at),
        "windows": lambda: sched.render_task_scheduler(cfg, args.at, command),
    }
    for name, render in pieces.items():
        if args.target in ("all", name):
            out.info(f"\n--- {name} ---\n{render()}")
    out.info(
        "\nSchedulers can delay or skip runs. Pulse never makes up for a missed run, and a "
        "second invocation on the same day is skipped."
    )
    return 0


def cmd_ledger(args: argparse.Namespace, out: Printer) -> int:
    env = _env(args)
    if args.action == "check":
        bad = reader.corrupt_lines(env.ledger_path)
        out.always(f"ledger: {env.ledger_path}")
        out.always("no malformed lines" if not bad else f"malformed lines: {bad}")
        return 0
    if not args.yes:
        raise E.UsageError("ledger prune rewrites the ledger; add --yes to confirm (a backup is made first)")
    dropped, backup = apply_retention(env.ledger_path, env.cfg["ledger"]["retention_days"])
    out.always(f"dropped {dropped} record(s)" + (f", backup at {backup}" if backup else ""))
    return 0


def cmd_validate(args: argparse.Namespace, out: Printer) -> int:
    path = resolve_config_path(_opt(args, "config"))
    cfg = load_config(path)
    out.info(f"{out.label('ok')} {path} is valid")
    for name in cfg.env_applied:
        out.info(f"  environment override applied: {name}")
    for warning in cfg.warnings:
        out.info(f"{out.label('warning')} {warning}")
    return 0


def cmd_doctor(args: argparse.Namespace, out: Printer) -> int:
    checks: list[tuple[str, str, str, int]] = []  # (label, status, detail, exit code if failed)

    def add(label: str, ok: bool, detail: str, code: int, warn: bool = False) -> None:
        checks.append((label, "ok" if ok else ("warning" if warn else "failed"), detail, code))

    add("python", sys.version_info >= (3, 11), sys.version.split()[0], E.EXIT_DEPENDENCY)
    add("pulse", True, __version__, 0)
    git_path = shutil.which("git")
    add("git installed", bool(git_path), git_path or "git was not found on PATH", E.EXIT_DEPENDENCY)
    env = None
    try:
        env = _env(args)
        add("configuration", True, str(env.config_path), E.EXIT_CONFIG)
    except E.PulseError as exc:
        add("configuration", False, str(exc), exc.exit_code)
    state = Path(_opt(args, "state_dir") or default_state_dir())
    if env:
        state = env.state_dir
    add("state directory writable", is_writable_dir(state), str(state), E.EXIT_PERSISTENCE)
    if env and git_path:
        git = GitCli(env.repo)
        if git.is_repository():
            snap = git.snapshot()
            add("repository", True, snap.root, E.EXIT_NOT_REPOSITORY)
            add("branch", True, f"{snap.branch or 'detached HEAD'}, "
                f"{'clean' if not snap.dirty else str(len(snap.dirty_paths)) + ' changed path(s)'}", 0)
            if snap.operation:
                add("operation in progress", False, snap.operation, 0, warn=True)
        else:
            add("repository", False, f"not a Git repository: {env.repo}", E.EXIT_NOT_REPOSITORY)
        lock = RunLock(env.state_dir / "locks" / f"{env.fingerprint.split(':')[-1][:12]}.lock")
        holder = lock.holder()
        add("run lock", holder is None, "free" if holder is None else f"held by pid {holder.get('pid')}",
            0, warn=True)
        plan = build_plan(env.cfg, PolicyEngine(env.cfg, env.repo))
        names = [f"{p.task_id}" for p in plan if p.status == "planned"]
        add("tasks planned", True, ", ".join(names) or "none", 0)
        for task_id in CONFIGURABLE:
            if not env.cfg["tasks"][task_id]["enabled"]:
                continue
            for argv in REGISTRY[task_id].command_lists(env.cfg):
                found = shutil.which(argv[0])
                add(f"executable {argv[0]}", bool(found), found or f"needed by {task_id}, not found",
                    E.EXIT_DEPENDENCY)
        bad = reader.corrupt_lines(env.ledger_path)
        add("ledger", not bad, "readable" if not bad else f"malformed lines: {bad[:10]}", 0, warn=True)
    if out.as_json:
        out.json([{"check": c[0], "status": c[1], "detail": c[2]} for c in checks])
    else:
        for label, status, detail, _ in checks:
            out.always(f"{out.label(status)} {label}: {detail}")
    failed = [code for _, status, _, code in checks if status == "failed"]
    if not failed:
        return 0
    return next((c for c in failed if c), E.EXIT_GENERAL)


def cmd_version(args: argparse.Namespace, out: Printer) -> int:
    out.always(f"pulse {__version__}")
    return 0


COMMAND_TABLE = {
    "init": cmd_init,
    "inspect": cmd_inspect,
    "plan": cmd_plan,
    "run": cmd_run,
    "report": cmd_report,
    "history": cmd_history,
    "tasks": cmd_tasks,
    "schedule": cmd_schedule,
    "ledger": cmd_ledger,
    "validate-config": cmd_validate,
    "doctor": cmd_doctor,
    "version": cmd_version,
}


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)  # bad arguments exit with code 2 and a usage hint
    configure_logging(_opt(args, "verbose", False), _opt(args, "quiet", False))
    out = _printer(args)
    try:
        return COMMAND_TABLE[args.command](args, out)
    except E.PulseError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return exc.exit_code
    except KeyboardInterrupt:
        print("interrupted", file=sys.stderr)
        return E.EXIT_INTERRUPTED


if __name__ == "__main__":
    raise SystemExit(main())
