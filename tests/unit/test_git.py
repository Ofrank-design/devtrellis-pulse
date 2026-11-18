import subprocess

import pytest

from devtrellis_pulse.core.errors import NotARepositoryError
from devtrellis_pulse.repository.git_cli import GitCli
from devtrellis_pulse.repository.status import parse_porcelain_z, sanitize_remote
from tests.helpers import git


def test_sanitize_remote_strips_credentials():
    assert sanitize_remote("https://user:tok3n@github.com/a/b.git") == "https://github.com/a/b.git"
    assert sanitize_remote("https://tok3n@github.com/a/b.git") == "https://github.com/a/b.git"
    assert sanitize_remote("git@github.com:a/b.git") == "git@github.com:a/b.git"
    assert sanitize_remote(None) is None


def test_parse_porcelain_handles_spaces_unicode_and_renames():
    raw = " M my file.txt\0?? café.txt\0R  new_name.txt\0old_name.txt\0"
    entries = parse_porcelain_z(raw)
    assert [e.path for e in entries] == ["my file.txt", "café.txt", "new_name.txt"]
    assert entries[1].untracked
    assert entries[2].orig_path == "old_name.txt"


def test_snapshot_reports_clean_and_dirty_states(repo):
    snap = GitCli(repo).snapshot()
    assert snap.branch == "main" and snap.head and not snap.dirty
    (repo / "README.md").write_text("changed\n")
    (repo / "new file.txt").write_text("x\n")
    (repo / "staged.txt").write_text("s\n")
    git(repo, "add", "staged.txt")
    snap = GitCli(repo).snapshot()
    assert snap.dirty_paths == {"README.md", "new file.txt", "staged.txt"}
    assert snap.staged_paths == {"staged.txt"}


def test_detached_head(repo):
    git(repo, "checkout", "-q", "--detach")
    assert GitCli(repo).snapshot().detached


def test_repository_without_commits(tmp_path):
    root = tmp_path / "empty"
    root.mkdir()
    git(root, "init", "-q", "-b", "main")
    snap = GitCli(root).snapshot()
    assert snap.head is None and snap.branch == "main"


def test_not_a_repository(tmp_path):
    with pytest.raises(NotARepositoryError):
        GitCli(tmp_path).snapshot()
    with pytest.raises(NotARepositoryError):
        GitCli(tmp_path / "missing").snapshot()


def test_paths_with_shell_characters_are_literal(repo):
    odd = repo / "a; touch pwned $(id).txt"
    odd.write_text("x\n")
    snap = GitCli(repo).snapshot()
    assert odd.name in snap.dirty_paths
    assert not (repo / "pwned").exists()


def test_merge_in_progress_is_detected(repo):
    git(repo, "checkout", "-q", "-b", "other")
    (repo / "README.md").write_text("other side\n")
    git(repo, "commit", "-qam", "other")
    git(repo, "checkout", "-q", "main")
    (repo / "README.md").write_text("main side\n")
    git(repo, "commit", "-qam", "main")
    subprocess.run(["git", "-C", str(repo), "merge", "other"], capture_output=True)
    assert GitCli(repo).snapshot().operation == "merge"


def test_shallow_clone_is_detected(repo, tmp_path):
    (repo / "more.txt").write_text("m\n")
    git(repo, "add", ".")
    git(repo, "commit", "-qm", "second")
    clone = tmp_path / "clone"
    subprocess.run(["git", "clone", "-q", "--depth", "1", f"file://{repo}", str(clone)], check=True)
    assert GitCli(clone).snapshot().shallow


def test_submodule_entries_are_listed(repo):
    git(repo, "update-index", "--add", "--cacheinfo", f"160000,{GitCli(repo).head()},vendor/lib")
    assert GitCli(repo).snapshot().submodules == ["vendor/lib"]


def test_remote_credentials_never_appear(repo):
    git(repo, "remote", "add", "origin", "https://user:secret123@example.com/x/y.git")
    snap = GitCli(repo).snapshot()
    assert snap.remote == "https://example.com/x/y.git"
    assert "secret123" not in str(snap)
