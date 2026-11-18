# Execution and the ledger

Tasks run sequentially. Every task gets a time limit, shares one operation budget and can be
cancelled. Retries happen only for tasks marked safe to retry.

The ledger is an append only JSON Lines file. Each event has an `event_id`, a
`schema_version` and a UTC timestamp. Secrets are redacted before anything is written. If a
line is damaged, `pulse ledger check` reports it and the reader skips it instead of failing.
Pruning old events is a deliberate command and always makes a backup first.
