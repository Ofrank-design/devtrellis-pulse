# Architecture overview

Pulse is a local Python program with no server. A run moves through these stages:

1. **Configuration** is loaded and validated. Command line options beat environment variables,
   which beat the file, which beats defaults.
2. **Inspection** reads the repository state through a small Git wrapper.
3. **Planning** decides which tasks are eligible and why, and records a reason for each.
4. **Policy** checks paths, permissions and preconditions before anything runs.
5. **Execution** runs tasks one at a time with timeouts, budgets and cancellation.
6. **Validation** scans changes for secrets and checks size and file type limits.
7. **Commit** stages only files Pulse produced, by explicit path, and commits them.
8. **Ledger and reports** record what happened in JSON Lines, Markdown and JSON.

State lives outside the repository in the user state directory, including the ledger, the run
lock and reports unless the operator asks for reports inside the repository.

Package layout under `src/devtrellis_pulse`: `core`, `platform`, `repository`, `policy`,
`validation`, `ledger`, `reports`, `execution`, `tasks`, `discovery`, `commits`, `scheduling`
and `app`. The command line in `cli.py` only calls the services in `app`.
