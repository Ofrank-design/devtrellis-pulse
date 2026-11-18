import os

import pytest

from devtrellis_pulse.core.errors import PolicyError
from devtrellis_pulse.policy.paths import PathPolicy, glob_to_regex


@pytest.fixture
def policy(tmp_path):
    (tmp_path / "reports" / "pulse").mkdir(parents=True)
    return PathPolicy(
        tmp_path,
        ["reports/pulse/**"],
        [".git/**", ".env", ".env.*", "**/*.pem", "**/id_rsa*"],
    )


def test_allowed_write(policy):
    assert policy.can_write("reports/pulse/run.md")


@pytest.mark.parametrize(
    "path",
    [
        "../escape.md",
        "reports/pulse/../../escape.md",
        "/etc/passwd",
        "C:/windows/x",
        "",
        "src/app.py",
        ".git/config",
        ".env",
        ".env.local",
        "reports/pulse/key.pem",
        "reports/pulse/id_rsa_backup",
        "reports\\..\\..\\x",
    ],
)
def test_blocked_paths(policy, path):
    with pytest.raises(PolicyError):
        policy.check_write(path)


def test_deny_beats_allow(tmp_path):
    p = PathPolicy(tmp_path, ["**"], ["secrets/**"])
    assert p.can_write("docs/a.md")
    assert not p.can_write("secrets/a.md")


def make_symlink(target, link):
    try:
        os.symlink(target, link)
    except OSError:
        pytest.skip("this system does not allow creating symbolic links")


def test_symlink_blocked(tmp_path, policy):
    outside = tmp_path.parent / "outside_target"
    outside.mkdir(exist_ok=True)
    make_symlink(outside, tmp_path / "reports" / "pulse" / "link")
    with pytest.raises(PolicyError, match="symbolic links"):
        policy.check_write("reports/pulse/link/x.md")


def test_symlink_escape_blocked_even_if_allowed(tmp_path):
    outside = tmp_path.parent / "outside_target2"
    outside.mkdir(exist_ok=True)
    (tmp_path / "reports").mkdir()
    make_symlink(outside, tmp_path / "reports" / "link")
    p = PathPolicy(tmp_path, ["reports/**"], [], allow_symlinks=True)
    with pytest.raises(PolicyError, match="outside"):
        p.check_write("reports/link/x.md")


def test_glob_semantics():
    assert glob_to_regex("a/**").match("a/b/c.txt")
    assert glob_to_regex("**/*.pem").match("x.pem")
    assert glob_to_regex("**/*.pem").match("a/b/x.pem")
    assert not glob_to_regex("*.md").match("a/b.md")
