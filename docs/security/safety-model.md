# Safety model

- Read only by default. Writing needs `runtime.mode: standard` and an allowed path.
- Denied paths always win over allowed paths.
- Subprocesses use argument lists, never a shell, with a scrubbed environment.
- Symlinks and path traversal are blocked.
- Staged content is scanned for secrets before any commit.
- Pulse stages explicit paths and uses `git commit --only`. It never uses `git add -A`,
  `reset --hard`, `clean`, `--amend`, custom dates or force push.
- Failures are reported as failures. Nothing is thrown away to recover.

The tests in `tests/acceptance/test_never_do.py` encode the list of things Pulse must never do.
