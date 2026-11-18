"""Print the CHANGELOG section for a version: python scripts/build_release_notes.py 0.1.0"""

import re
import sys
from pathlib import Path


def main(version: str) -> int:
    text = Path("CHANGELOG.md").read_text(encoding="utf-8")
    match = re.search(rf"^## \[?{re.escape(version)}\]?.*?(?=^## |\Z)", text, re.S | re.M)
    if not match:
        print(f"no changelog entry for {version}", file=sys.stderr)
        return 1
    print(match.group(0).strip())
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else ""))
