"""Built in tasks, exercised through the engine so the full contract is in play."""

import pytest

from tests.helpers import execute, git, make_cfg, task


def docs(repo, **task_cfg):
    cfg = make_cfg(tasks={"documentation": task_cfg})
    return task(execute(cfg, repo, only=["documentation"]), "documentation")


def messages(result):
    return [f.message for f in result.findings]


# ---- documentation guardian -------------------------------------------------------------


def test_a_healthy_documentation_tree_passes(repo):
    result = docs(repo)
    assert result.status == "passed" and not result.findings


def test_missing_required_file_is_a_finding(repo):
    (repo / "LICENSE").unlink()
    result = docs(repo)
    assert result.status == "failed"
    assert any("LICENSE" == f.path for f in result.findings)


def test_broken_local_link_is_a_finding(repo):
    (repo / "README.md").write_text("# T\n\nSee [guide](docs/guide.md) and [site](https://example.com).\n")
    result = docs(repo)
    assert result.status == "failed" and any("docs/guide.md" in m for m in messages(result))
    (repo / "docs").mkdir()
    (repo / "docs" / "guide.md").write_text("# Guide\n")
    assert docs(repo).status == "passed"


def test_links_inside_code_fences_are_ignored(repo):
    (repo / "README.md").write_text("# T\n\n```md\n[example](nowhere.md)\n```\n")
    assert docs(repo).status == "passed"


def test_anchor_links_and_urls_are_not_file_checks(repo):
    (repo / "README.md").write_text("# T\n\n[a](#section) [b](https://x.org) [c](mailto:a@b.c)\n")
    assert docs(repo).status == "passed"


def test_unbalanced_code_fence_is_reported(repo):
    (repo / "README.md").write_text("# T\n\n```python\nprint(1)\n")
    result = docs(repo)
    assert result.status == "failed" and "unbalanced code fence" in messages(result)


def test_heading_jumps_warn_but_do_not_fail(repo):
    (repo / "README.md").write_text("# T\n\n### Deep\n")
    result = docs(repo)
    assert result.status == "passed"
    assert any(f.severity == "warning" and "jumps" in f.message for f in result.findings)


def test_forbidden_markers_and_required_sections(repo):
    (repo / "README.md").write_text("# T\n\n## Install\n\nTODO write this\n")
    result = docs(repo, forbidden_markers=["TODO"], required_readme_sections=["Install", "Usage"])
    assert result.status == "failed"
    assert any("TODO" in m for m in messages(result))
    assert any("Usage" in m for m in messages(result))
    assert not any("Install" in m for m in messages(result))


def test_invalid_example_configuration_is_found(repo):
    (repo / "pulse.example.yml").write_text("version: 2\n")
    result = docs(repo)
    assert result.status == "failed" and any("does not parse" in m for m in messages(result))


def write_cfg(**overrides):
    base = {
        "runtime": {"mode": "standard"},
        "policy": {"allowed_write_paths": ["docs/generated/**", "reports/pulse/**"]},
        "tasks": {
            "documentation": {"mode": "write", "generated_cli_reference": "docs/generated/cli.md"}
        },
    }
    base.update(overrides)
    return make_cfg(**base)


def commit_all(repo, message="update"):
    git(repo, "add", ".")
    git(repo, "commit", "-qm", message)


def test_generated_reference_is_created_then_is_stable(repo):
    first = task(execute(write_cfg(), repo, only=["documentation"]), "documentation")
    assert first.changed_paths == ["docs/generated/cli.md"]
    text = (repo / "docs/generated/cli.md").read_text()
    assert "pulse:cli-reference:start" in text and "`pulse run`" in text
    commit_all(repo)
    second = task(execute(write_cfg(), repo, only=["documentation"]), "documentation")
    assert second.status == "no_changes" and second.changed_paths == []


def test_hand_written_prose_around_the_markers_is_preserved(repo):
    target = repo / "docs" / "generated"
    target.mkdir(parents=True)
    (target / "cli.md").write_text(
        "# My notes\n\nKeep this.\n\n<!-- pulse:cli-reference:start -->\nold\n"
        "<!-- pulse:cli-reference:end -->\n\nAnd keep this too.\n"
    )
    commit_all(repo)
    result = task(execute(write_cfg(), repo, only=["documentation"]), "documentation")
    assert result.changed_paths == ["docs/generated/cli.md"]
    text = (target / "cli.md").read_text()
    assert "Keep this." in text and "And keep this too." in text and "old\n" not in text


def test_missing_markers_mean_no_write(repo):
    target = repo / "docs" / "generated"
    target.mkdir(parents=True)
    (target / "cli.md").write_text("# Hand written, no markers\n")
    commit_all(repo)
    result = task(execute(write_cfg(), repo, only=["documentation"]), "documentation")
    assert result.status == "failed" and result.changed_paths == []
    assert (target / "cli.md").read_text() == "# Hand written, no markers\n"


def test_check_mode_reports_drift_without_writing(repo):
    cfg = make_cfg(
        tasks={"documentation": {"generated_cli_reference": "docs/generated/cli.md"}}
    )
    result = task(execute(cfg, repo, only=["documentation"]), "documentation")
    assert result.status == "passed"
    assert any("missing" in m for m in messages(result))
    assert not (repo / "docs").exists()


# ---- dependency inventory ---------------------------------------------------------------


def inventory(repo):
    return task(execute(make_cfg(), repo, only=["dependency_inventory"]), "dependency_inventory")


def test_no_manifests(repo):
    result = inventory(repo)
    assert result.summary == "no dependency manifests" and result.status == "passed"


def test_manifests_are_counted_and_lockfiles_checked(repo):
    (repo / "pyproject.toml").write_text(
        '[project]\nname = "x"\ndependencies = ["a", "b"]\n'
        "[project.optional-dependencies]\ndev = [\"c\"]\n"
    )
    (repo / "requirements.txt").write_text("# comment\nrequests==2.0\n\nflask\n-r other.txt\n")
    (repo / "package.json").write_text('{"dependencies": {"a": "1"}, "devDependencies": {"b": "1"}}')
    (repo / "go.mod").write_text("module m\n\nrequire (\n\tgithub.com/a/b v1.0.0\n\tgithub.com/c/d v2.0.0\n)\n")
    result = inventory(repo)
    counts = result.metrics["manifests"]
    assert counts == {"go.mod": 2, "package.json": 2, "pyproject.toml": 3, "requirements.txt": 2}
    warned = {f.path for f in result.findings if f.severity == "warning"}
    assert warned == {"package.json", "go.mod"}  # no lockfile or checksum file present
    (repo / "package-lock.json").write_text("{}")
    assert "package-lock.json" in inventory(repo).metrics["lockfiles"]


def test_unparseable_manifests_are_reported_without_guessing(repo):
    (repo / "package.json").write_text("{ nope")
    (repo / "setup.py").write_text("from setuptools import setup\n")
    result = inventory(repo)
    assert result.metrics["manifests"]["package.json"] is None
    assert result.metrics["manifests"]["setup.py"] is None
    assert not any("vulnerab" in f.message.lower() for f in result.findings)


# ---- repository health ------------------------------------------------------------------


def health(repo, cfg=None):
    return task(execute(cfg or make_cfg(), repo, only=["repository_health"]), "repository_health")


def test_health_reports_facts_not_scores(repo):
    result = health(repo)
    m = result.metrics
    assert m["tracked_files"] == 2 and m["has_readme"] and m["has_license"]
    assert not m["has_security_policy"] and not m["has_ci_workflows"]
    assert not any(k in m for k in ("score", "grade", "rating"))
    optional = [f for f in result.findings if f.severity == "info"]
    assert optional and all("optional" in f.message for f in optional)


def test_health_notices_ci_tests_and_large_files(repo):
    (repo / ".github" / "workflows").mkdir(parents=True)
    (repo / ".github" / "workflows" / "ci.yml").write_text("name: ci\n")
    (repo / "tests").mkdir()
    (repo / "big.bin").write_bytes(b"x" * 1_100_000)
    commit_all(repo)
    result = health(repo)
    assert result.metrics["has_ci_workflows"] and result.metrics["has_tests"]
    assert result.metrics["large_files"] == 1
    assert any(f.path == "big.bin" and f.severity == "warning" for f in result.findings)


def test_health_snapshot_file_is_deterministic(repo):
    cfg = make_cfg(runtime={"mode": "standard"}, tasks={"repository_health": {"write_snapshot": True}})
    first = health(repo, cfg)
    assert first.changed_paths == ["reports/pulse/health.md"]
    commit_all(repo)
    second = health(repo, cfg)
    assert second.status == "no_changes" and second.changed_paths == []
    assert "no combined score" in (repo / "reports/pulse/health.md").read_text()


@pytest.mark.parametrize("name", ["tests", "code_hygiene"])
def test_tasks_that_run_repository_code_are_off_by_default(repo, name):
    run = execute(make_cfg(), repo)
    assert task(run, name).status == "skipped"
