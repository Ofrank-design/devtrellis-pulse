import json
import os
import sys
import threading
import time

import pytest

from devtrellis_pulse.core.errors import BudgetExceeded, LockError
from devtrellis_pulse.execution.cancellation import CancellationToken
from devtrellis_pulse.execution.limits import Budget, ChangeTracker
from devtrellis_pulse.platform.process import run_command, scrubbed_env
from devtrellis_pulse.scheduling.lock import RunLock


def test_budget_counts_operations():
    budget = Budget(2, 60)
    budget.spend()
    budget.spend()
    with pytest.raises(BudgetExceeded):
        budget.spend()


def test_budget_stops_at_the_deadline():
    budget = Budget(10, 0.01)
    time.sleep(0.05)
    with pytest.raises(BudgetExceeded, match="time"):
        budget.spend()


def test_change_tracker_limits_files_and_bytes():
    tracker = ChangeTracker(max_files=2, max_bytes=100)
    tracker.record("a", 10)
    tracker.record("b", 10)
    tracker.record("b", 20)  # rewriting the same file does not count twice
    with pytest.raises(BudgetExceeded, match="files"):
        tracker.record("c", 1)
    bytes_tracker = ChangeTracker(max_files=10, max_bytes=50)
    bytes_tracker.record("a", 40)
    with pytest.raises(BudgetExceeded, match="bytes"):
        bytes_tracker.record("b", 20)


# ---- subprocess runner ------------------------------------------------------------------


def test_runner_success_failure_and_missing_executable(tmp_path):
    ok = run_command([sys.executable, "-c", "print('hi')"], tmp_path, 10, 1000)
    assert ok.ok and "hi" in ok.output
    bad = run_command([sys.executable, "-c", "raise SystemExit(3)"], tmp_path, 10, 1000)
    assert bad.returncode == 3 and not bad.ok
    assert run_command(["definitely-not-a-binary"], tmp_path, 10, 1000).returncode == 127


def test_runner_enforces_the_timeout(tmp_path):
    started = time.monotonic()
    slow = run_command([sys.executable, "-c", "import time; time.sleep(30)"], tmp_path, 0.5, 1000)
    assert slow.timed_out and not slow.ok
    assert time.monotonic() - started < 10


def test_runner_bounds_output_memory(tmp_path):
    result = run_command([sys.executable, "-c", "print('x' * 200000)"], tmp_path, 10, 100)
    assert result.truncated and len(result.output) <= 100


def test_runner_never_uses_a_shell(tmp_path):
    marker = tmp_path / "pwned"
    result = run_command(
        [sys.executable, "-c", "import sys; print(sys.argv[1])", f"hi; touch {marker}"], tmp_path, 10, 1000
    )
    assert result.ok and not marker.exists()


def test_runner_can_be_cancelled(tmp_path):
    token = CancellationToken()
    threading.Timer(0.3, token.cancel).start()
    started = time.monotonic()
    result = run_command([sys.executable, "-c", "import time; time.sleep(30)"], tmp_path, 20, 1000, token)
    assert result.cancelled and time.monotonic() - started < 10


def test_environment_is_scrubbed(monkeypatch):
    monkeypatch.setenv("MY_API_TOKEN", "abc")
    monkeypatch.setenv("DB_PASSWORD", "abc")
    monkeypatch.setenv("HARMLESS", "1")
    env = scrubbed_env()
    assert "MY_API_TOKEN" not in env and "DB_PASSWORD" not in env
    assert env["HARMLESS"] == "1"


def test_child_processes_do_not_see_secrets(tmp_path, monkeypatch):
    monkeypatch.setenv("SERVICE_SECRET", "topsecret")
    result = run_command(
        [sys.executable, "-c", "import os; print(os.environ.get('SERVICE_SECRET'))"], tmp_path, 10, 1000
    )
    assert "topsecret" not in result.output


# ---- run lock ---------------------------------------------------------------------------


def test_lock_is_exclusive_and_released(tmp_path):
    path = tmp_path / "run.lock"
    with RunLock(path):
        with pytest.raises(LockError):
            RunLock(path).acquire()
    assert not path.exists()


def test_lock_recovers_from_a_dead_owner(tmp_path):
    path = tmp_path / "run.lock"
    import socket

    path.write_text(json.dumps({"pid": 2**22 + 777, "hostname": socket.gethostname()}))
    with RunLock(path):
        assert json.loads(path.read_text())["pid"] == os.getpid()


def test_lock_never_breaks_a_live_owner_however_old(tmp_path):
    import socket

    path = tmp_path / "run.lock"
    path.write_text(json.dumps({"pid": os.getpid(), "hostname": socket.gethostname(), "started_at": "2001-01-01T00:00:00Z"}))
    old = time.time() - 10 * 365 * 86400
    os.utime(path, (old, old))
    with pytest.raises(LockError):
        RunLock(path).acquire()


def test_lock_on_another_host_is_never_stolen(tmp_path):
    path = tmp_path / "run.lock"
    path.write_text(json.dumps({"pid": 2**22 + 5, "hostname": "some-other-machine"}))
    with pytest.raises(LockError):
        RunLock(path).acquire()


def test_malformed_lock_file_is_replaced(tmp_path):
    path = tmp_path / "run.lock"
    path.write_text("not json")
    with RunLock(path):
        assert RunLock(path).holder()["pid"] == os.getpid()


def test_lock_can_wait_a_bounded_time(tmp_path):
    path = tmp_path / "run.lock"
    holder = RunLock(path)
    holder.acquire()
    threading.Timer(0.4, holder.release).start()
    with RunLock(path, wait_seconds=5):
        pass
    holder2 = RunLock(path)
    holder2.acquire()
    started = time.monotonic()
    with pytest.raises(LockError):
        RunLock(path, wait_seconds=0.5).acquire()
    assert 0.4 < time.monotonic() - started < 5


def test_pid_check_sees_this_process_and_a_dead_one():
    from devtrellis_pulse.scheduling.lock import _pid_alive

    assert _pid_alive(os.getpid())
    assert not _pid_alive(2**22 + 777)


def test_pid_check_never_signals_on_windows():
    # os.kill(pid, 0) sends Ctrl+C on Windows, so the code must not reach it there.
    import inspect

    from devtrellis_pulse.scheduling import lock

    source = inspect.getsource(lock._pid_alive)
    assert source.index('sys.platform == "win32"') < source.index("os.kill")
