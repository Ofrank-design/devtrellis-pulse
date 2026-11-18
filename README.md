# DevTrellis Pulse

DevTrellis Pulse is a local command line tool that keeps a Git repository in good shape. It
checks documentation, runs the tests and linters you choose, records what it found, and can
commit its own report files when you allow it. It runs on your machine and needs no server.

Pulse is not a tool for making a repository look busy. It never makes random edits, empty
commits, whitespace changes or backdated commits. A run with zero commits is a normal,
successful run, and a quiet repository gets an honest report that says nothing changed.

Early release, version 0.1.0. Windows support is new and has had limited testing, and pushing to a remote has only been tried
against a local test remote. Please read the reports it writes before trusting it with a
repository you care about.

## Install

```bash
python -m pip install -e .
```

Python 3.11 or newer and Git are required.

## First run

```bash
pulse init               # create pulse.yml with safe defaults
pulse validate-config
pulse inspect            # look at the repository, changes nothing
pulse plan               # show what would run and why
pulse run --execute      # run the planned tasks
pulse report --latest
```

`pulse run` on its own is a dry run. You must pass `--execute` to run tasks. Commits are off
until you enable them in the configuration and set `runtime.mode: standard`.

## Commands

The full table is in [docs/reference/cli.md](docs/reference/cli.md). The main ones are `init`,
`inspect`, `plan`, `run`, `report`, `history`, `tasks`, `schedule`, `ledger`,
`validate-config` and `doctor`.

## What it will not do

Pulse never uses `git add -A`, `reset --hard`, `clean`, `--amend`, custom commit dates or force
push. It does not commit files you changed yourself, and it stops before running if your
working tree is not clean. See [docs/security/safety-model.md](docs/security/safety-model.md).

## Scheduling

Pulse has no background process. Use cron, a systemd timer, Task Scheduler or GitHub Actions to
call `pulse run --scheduled --execute`, and `pulse schedule` prints a snippet for each. Schedulers
can delay or skip runs, and Pulse does not catch up on missed ones.

## Exit codes

0 means success. Codes 1 to 12 describe what went wrong, and 130 means the run was
interrupted. See [docs/reference/exit-codes.md](docs/reference/exit-codes.md).

## Project

Frank Oduro leads the project and has final say on everything. See [AUTHORS.md](AUTHORS.md),
[GOVERNANCE.md](GOVERNANCE.md) and [CONTRIBUTING.md](CONTRIBUTING.md). Licensed under the
Apache License 2.0, copyright Frank Oduro.
