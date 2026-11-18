"""Check that local Markdown links resolve across the repository docs."""

import re
import sys
from pathlib import Path

LINK = re.compile(r"\[[^\]]*\]\(([^)#\s]+)")


def main() -> int:
    bad = 0
    for md in [*Path(".").glob("*.md"), *Path("docs").rglob("*.md"), *Path("examples").rglob("*.md")]:
        text = re.sub(r"```.*?```", "", md.read_text(encoding="utf-8"), flags=re.S)
        for target in LINK.findall(text):
            if "://" in target or target.startswith("mailto:"):
                continue
            if not (md.parent / target).exists():
                bad += 1
                print(f"{md}: broken link {target}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
