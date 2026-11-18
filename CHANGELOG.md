# Changelog

Format follows Keep a Changelog and Semantic Versioning.

## [0.1.0] - 2026-11-03

First release.

### Fixed
- Windows: timezone lookup no longer fails without a timezone database (adds `tzdata` on Windows), stopping a timed out or cancelled command now ends its whole process tree

### Added
- The `pulse` command with init, inspect, plan, run, report, history, tasks, schedule, ledger,
  validate-config, doctor and version
- Strict configuration with a clear order of precedence and a starter file
- Planner that gives a reason for every task it plans or skips
- Safe execution engine with time limits, an operation budget, cancellation and a run lock
- Built in tasks: documentation, tests, code hygiene, repository health, dependency inventory
  and activity report
- Append only JSON Lines ledger, Markdown and JSON reports
- Commit manager that is off by default, stages explicit paths only and scans for secrets
- Scheduling snippets for cron, systemd, GitHub Actions and Windows Task Scheduler
- Tests that encode the list of things Pulse must never do
