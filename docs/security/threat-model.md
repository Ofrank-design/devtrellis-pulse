# Threat model

Main risks and the answer to each:

| Risk | Answer |
|---|---|
| Unwanted changes to a repository | Dry run by default, path allowlist, clean start rule |
| Secrets leaking into commits or reports | Secret scan and redaction before writing |
| Running untrusted repository code | Code running tasks are off by default and run without a shell |
| Two runs at once | Per repository lock with identity checks |
| Misleading activity | No empty, backdated or repeated commits, by design |
