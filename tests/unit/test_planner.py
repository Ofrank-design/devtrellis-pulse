import pytest

from devtrellis_pulse.core.errors import ConfigError
from devtrellis_pulse.discovery.planner import build_plan
from devtrellis_pulse.policy.engine import PolicyEngine
from tests.helpers import make_cfg


def plan_for(cfg, tmp_path, **kwargs):
    return {p.task_id: p for p in build_plan(cfg, PolicyEngine(cfg, tmp_path), **kwargs)}


def test_enabled_and_disabled_tasks(tmp_path):
    plan = plan_for(make_cfg(), tmp_path)
    assert plan["documentation"].status == "planned"
    assert plan["tests"].status == "skipped" and "disabled" in plan["tests"].reason
    assert plan["activity_report"].status == "skipped"


def test_every_decision_has_a_reason(tmp_path):
    assert all(p.reason for p in plan_for(make_cfg(), tmp_path).values())


def test_subprocess_tasks_are_blocked_without_permission(tmp_path):
    cfg = make_cfg(tasks={"tests": {"enabled": True}}, policy={"allow_subprocesses": False})
    plan = plan_for(cfg, tmp_path)
    assert plan["tests"].status == "blocked" and "subprocesses" in plan["tests"].reason


def test_write_tasks_are_blocked_in_safe_mode_at_plan_time(tmp_path):
    cfg = make_cfg(runtime={"mode": "standard"}, reports={"write_to_repository": True})
    assert plan_for(cfg, tmp_path)["activity_report"].status == "planned"


def test_tasks_with_nothing_configured_are_skipped(tmp_path):
    cfg = make_cfg(tasks={"tests": {"enabled": True, "commands": []}})
    assert plan_for(cfg, tmp_path)["tests"].reason == "no commands configured"


def test_operation_budget_is_an_upper_bound(tmp_path):
    cfg = make_cfg(runtime={"max_operations_per_run": 2})
    planned = [p for p in plan_for(cfg, tmp_path).values() if p.status == "planned"]
    assert sum(p.operations for p in planned) <= 2
    skipped = [p for p in plan_for(cfg, tmp_path).values() if "budget" in p.reason]
    assert skipped


def test_only_filter_and_unknown_task(tmp_path):
    plan = plan_for(make_cfg(), tmp_path, only=["repository_health"])
    assert [k for k, v in plan.items() if v.status == "planned"] == ["repository_health"]
    with pytest.raises(ConfigError, match="unknown task"):
        plan_for(make_cfg(), tmp_path, only=["nope"])


def test_duplicate_commands_run_once(tmp_path):
    same = [["python", "-m", "pytest"]]
    cfg = make_cfg(
        tasks={
            "tests": {"enabled": True, "commands": same},
            "code_hygiene": {"enabled": True, "commands": same},
        }
    )
    plan = plan_for(cfg, tmp_path)
    assert plan["tests"].status == "planned"
    assert plan["code_hygiene"].reason == "duplicate of tests"


def test_conflicting_write_scopes_are_blocked(tmp_path):
    cfg = make_cfg(
        runtime={"mode": "standard"},
        policy={"allowed_write_paths": ["reports/pulse/**"]},
        tasks={"repository_health": {"write_snapshot": True}},
        reports={"write_to_repository": True},
    )
    plan = plan_for(cfg, tmp_path)
    assert plan["repository_health"].status == "planned"
    assert plan["activity_report"].status == "blocked"
    assert "conflicts" in plan["activity_report"].reason


def test_plans_are_deterministic(tmp_path):
    cfg = make_cfg()
    one = [p.__dict__ for p in build_plan(cfg, PolicyEngine(cfg, tmp_path))]
    two = [p.__dict__ for p in build_plan(cfg, PolicyEngine(cfg, tmp_path))]
    assert one == two


def test_plan_lists_expected_write_scope(tmp_path):
    cfg = make_cfg(
        runtime={"mode": "standard"},
        tasks={"repository_health": {"write_snapshot": True}},
    )
    assert plan_for(cfg, tmp_path)["repository_health"].write_paths == ["reports/pulse/health.md"]


def test_history_feeds_estimates_but_never_promises(tmp_path):
    plan = plan_for(make_cfg(), tmp_path, estimates={"documentation": 1.5})
    assert plan["documentation"].estimated_seconds == 1.5
    assert plan["repository_health"].estimated_seconds is None
