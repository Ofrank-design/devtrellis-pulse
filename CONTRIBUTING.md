# Contributing

## Setup

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
```

## Checks

```bash
python -m pytest
ruff check src tests
```

## Process

1. For large changes, open an issue first.
2. Branch from `main`, keep changes focused and avoid unrelated formatting churn.
3. Add tests for every bug fix and feature, including failure paths.
4. Update docs and `CHANGELOG.md` for user visible changes.
5. Open a pull request and complete the checklist below.

## Commit messages

Use the form `type(scope): summary`, for example `fix(policy): block symlink escape`.

## Pull request checklist

- Tests cover expected behavior and failure paths
- Security implications are considered
- No secrets or personal data
- Task permission declarations are accurate and path scope is narrow
- Commit behavior stays safe, with no random or empty commits
- Docs and changelog updated

## Rights

By contributing you confirm that you have the right to submit the work under the Apache License 2.0.

## Who decides

Frank Oduro, the lead maintainer, reviews and decides on every contribution. See [GOVERNANCE.md](GOVERNANCE.md) and [AUTHORS.md](AUTHORS.md).
