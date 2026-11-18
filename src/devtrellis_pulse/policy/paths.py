"""Path policy: every read, write or commit candidate is checked here. Deny rules always win."""

from __future__ import annotations

import os
import re
from pathlib import Path, PurePosixPath

from devtrellis_pulse.core.errors import PolicyError


def glob_to_regex(pattern: str) -> re.Pattern[str]:
    out: list[str] = []
    i = 0
    while i < len(pattern):
        char = pattern[i]
        if char == "*":
            if pattern.startswith("**/", i):
                out.append("(?:.*/)?")
                i += 3
                continue
            if pattern.startswith("**", i):
                out.append(".*")
                i += 2
                continue
            out.append("[^/]*")
        elif char == "?":
            out.append("[^/]")
        else:
            out.append(re.escape(char))
        i += 1
    return re.compile("^" + "".join(out) + "$")


def normalize_relative(path: str) -> str:
    """Return a clean repository relative POSIX path or raise PolicyError."""
    if not isinstance(path, str) or not path or "\0" in path:
        raise PolicyError("empty or invalid path")
    candidate = path.replace("\\", "/")
    if candidate.startswith("/") or re.match(r"^[A-Za-z]:", candidate):
        raise PolicyError(f"absolute paths are not allowed: {path}")
    parts = PurePosixPath(candidate).parts
    if ".." in parts:
        raise PolicyError(f"path traversal is not allowed: {path}")
    clean = "/".join(p for p in parts if p != ".")
    if not clean:
        raise PolicyError("empty or invalid path")
    return clean


class PathPolicy:
    def __init__(
        self,
        repo_root: Path,
        allowed_write: list[str],
        denied: list[str],
        allow_symlinks: bool = False,
        allowed_read: list[str] | None = None,
    ) -> None:
        self.root = Path(repo_root).resolve()
        self.allowed_write = [(p, glob_to_regex(p)) for p in allowed_write]
        self.allowed_read = [(p, glob_to_regex(p)) for p in (allowed_read or ["**"])]
        self.denied = [(p, glob_to_regex(p)) for p in denied]
        self.allow_symlinks = allow_symlinks

    @staticmethod
    def _matches(rules: list[tuple[str, re.Pattern[str]]], rel: str) -> bool:
        base = rel.rsplit("/", 1)[-1]
        for pattern, regex in rules:
            if regex.match(rel):
                return True
            if "/" not in pattern and regex.match(base):
                return True
        return False

    def is_denied(self, rel: str) -> bool:
        return self._matches(self.denied, rel)

    def is_allowed(self, rel: str) -> bool:
        """True when the path matches the write allowlist (deny rules are checked separately)."""
        return self._matches(self.allowed_write, rel)

    def _check_symlinks(self, rel: str) -> Path:
        current = self.root
        for part in rel.split("/"):
            current = current / part
            if os.path.islink(current) and not self.allow_symlinks:
                raise PolicyError(f"symbolic links are blocked: {rel}")
        resolved = current.resolve()
        if resolved != self.root and self.root not in resolved.parents:
            raise PolicyError(f"path resolves outside the repository: {rel}")
        return resolved

    def check_write(self, path: str) -> Path:
        rel = normalize_relative(path)
        if self.is_denied(rel):
            raise PolicyError(f"path is denied by policy: {rel}")
        if not self.is_allowed(rel):
            raise PolicyError(f"path is not in allowed_write_paths: {rel}")
        return self._check_symlinks(rel)

    def check_read(self, path: str) -> Path:
        rel = normalize_relative(path)
        if self.is_denied(rel):
            raise PolicyError(f"path is denied by policy: {rel}")
        if not self._matches(self.allowed_read, rel):
            raise PolicyError(f"path is not in allowed_read_paths: {rel}")
        return self._check_symlinks(rel)

    def can_write(self, path: str) -> bool:
        try:
            self.check_write(path)
        except PolicyError:
            return False
        return True
