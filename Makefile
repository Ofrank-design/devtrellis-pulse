.PHONY: install test lint docs

install:
	python -m pip install -e ".[dev]"

test:
	python -m pytest

lint:
	ruff check .

docs:
	python scripts/check_docs.py
