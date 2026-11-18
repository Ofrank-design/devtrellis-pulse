# Testing

```bash
python -m pip install -e ".[dev]"
python -m pytest
ruff check .
```

Tests use disposable Git repositories created under a temporary directory and an isolated
state directory, so they never touch your real repositories or ledger.
