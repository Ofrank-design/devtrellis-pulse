"""Validate every example configuration. Used by CI and `make docs`."""

import sys
from pathlib import Path

from devtrellis_pulse.core.config import load_config
from devtrellis_pulse.core.errors import ConfigError


def main() -> int:
    failed = 0
    for path in sorted(Path("examples").glob("*/pulse.yml")) + [Path("pulse.example.yml")]:
        if "github-actions" in path.parts:
            continue
        try:
            load_config(path)
            print(f"ok     {path}")
        except ConfigError as exc:
            failed += 1
            print(f"FAILED {path}: {exc}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
