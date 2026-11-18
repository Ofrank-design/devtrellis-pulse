# Exit codes

| Code | Name | Meaning |
|---|---|---|
| 0 | OK | The run finished and nothing needs attention. Zero commits is still success. |
| 1 | General error | Something unexpected went wrong. |
| 2 | Usage error | The command line was wrong. |
| 3 | Configuration error | The configuration file is missing or invalid. |
| 4 | Not a repository | The target is not a usable Git repository. |
| 5 | Policy blocked | A policy rule stopped the run before it started. |
| 6 | Locked | Another Pulse run holds the lock for this repository. |
| 7 | Tasks failed | One or more tasks failed, timed out or were blocked. |
| 8 | Validation failed | Changes failed validation, for example a secret was found. |
| 9 | Commit failed | Creating or pushing a commit failed. |
| 10 | Dependency missing | A required tool is not installed. |
| 11 | Budget exceeded | An operation, runtime or change limit stopped the run. |
| 12 | Persistence failed | The ledger or a report could not be written. |
| 130 | Interrupted | The run was cancelled with Ctrl+C or a termination signal. |

When several conditions apply, the most serious wins in this order:
130, 12, 9, 8, 11, 7.
