"""Single source of truth for the command inventory (specification 10.1)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CommandSpec:
    name: str
    summary: str
    writes: str


COMMANDS: tuple[CommandSpec, ...] = (
    CommandSpec("init", "Create starter config", "Config only"),
    CommandSpec("inspect", "Inspect repository", "No"),
    CommandSpec("plan", "Preview eligible tasks", "No"),
    CommandSpec("run", "Execute approved tasks", "Possibly"),
    CommandSpec("report", "Render run report", "No"),
    CommandSpec("history", "List previous runs", "No"),
    CommandSpec("tasks", "List task registry", "No"),
    CommandSpec("schedule", "Show scheduler snippets for cron, systemd or GitHub Actions", "No"),
    CommandSpec("ledger", "Check or prune the activity ledger", "Ledger only"),
    CommandSpec("validate-config", "Validate config", "No"),
    CommandSpec("doctor", "Diagnose installation", "No"),
    CommandSpec("version", "Print version", "No"),
)

CLI_REFERENCE_START = "<!-- pulse:cli-reference:start -->"
CLI_REFERENCE_END = "<!-- pulse:cli-reference:end -->"


def cli_reference_markdown() -> str:
    """Deterministic Markdown for the generated CLI reference section."""
    lines = [
        "| Command | Purpose | Writes repository files? |",
        "|---|---|---|",
    ]
    lines += [f"| `pulse {c.name}` | {c.summary} | {c.writes} |" for c in COMMANDS]
    return "\n".join(lines)
