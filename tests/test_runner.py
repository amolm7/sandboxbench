import json
import threading

import pytest

from sandboxbench.backends import LocalBackend
from sandboxbench.cli import main
from sandboxbench.report import render_report
from sandboxbench.runner import Config, resolve_candidates, run_benchmark, run_single
from sandboxbench.tasks import TASKS


class FakeBackend:
    sandbox_id = "fake-sandbox"

    def __init__(self, fail_start=False, fail_close=False, fail_execute=False):
        self.fail_start = fail_start
        self.fail_close = fail_close
        self.fail_execute = fail_execute
        self.closed = False

    def start(self, lifetime):
        if self.fail_start:
            raise RuntimeError("create failed")

    def execute(self, program, timeout):
        if self.fail_execute:
            raise RuntimeError("transport failed")
        return dict(
            status="passed",
            tests_run=len(TASKS[0].checks),
            failures=0,
            errors=0,
            stdout="",
            stderr="",
            trace="ok",
        )

    def close(self):
        self.closed = True
        if self.fail_close:
            raise RuntimeError("kill failed")


@pytest.mark.parametrize("failure", ["fail_start", "fail_execute", "fail_close"])
def test_cleanup_and_failure_artifacts(tmp_path, failure):
    backend = FakeBackend(**{failure: True})
    config = Config(runs=1)
    run = run_single(
        1,
        "reference",
        resolve_candidates(("reference",))["reference"],
        config,
        tmp_path,
        lambda: backend,
        tasks=(TASKS[0],),
    )
    assert backend.closed
    assert (tmp_path / "run-001" / "run.json").is_file()
    if failure == "fail_execute":
        assert run["tasks"][0]["status"] == "error"
        assert run["pass_rate"] == 0
    else:
        assert run["status"] == "error"
        assert run["cost_uncertain"]
        assert run["cost_basis_seconds"] >= config.sandbox_timeout


def test_parallel_runs_really_overlap_and_bound_workers(tmp_path):
    barrier = threading.Barrier(2, timeout=5)
    lock = threading.Lock()
    active, peak = 0, 0

    class ConcurrentBackend(FakeBackend):
        def start(self, lifetime):
            nonlocal active, peak
            with lock:
                active += 1
                peak = max(peak, active)
            barrier.wait()

        def execute(self, program, timeout):
            # Real local test harness, with a fake sandbox lifecycle.
            return LocalBackend().execute(program, timeout)

        def close(self):
            nonlocal active
            with lock:
                active -= 1

    result = run_benchmark(
        Config(backend="local", runs=4, concurrency=2), tmp_path / "parallel", ConcurrentBackend
    )
    assert peak == 2
    assert active == 0
    assert [r["id"] for r in result["runs"]] == [f"run-{i:03d}" for i in range(1, 5)]
    assert all(r["passed"] == 10 for r in result["runs"])


def test_infrastructure_failure_keeps_full_denominator(tmp_path):
    result = run_benchmark(
        Config(runs=2), tmp_path / "errors", lambda: FakeBackend(fail_start=True)
    )
    assert all(r["total"] == 10 and r["pass_rate"] == 0 for r in result["runs"])
    render_report(result, tmp_path / "errors" / "report.html")
    assert "0/20 scheduled tasks" in (tmp_path / "errors" / "report.html").read_text()


def test_report_escapes_traces_and_links_exist(tmp_path):
    root = tmp_path / "report"
    result = run_benchmark(Config(backend="local", runs=1), root)
    result["runs"][0]["tasks"][0]["trace"] = "<script>alert('x')</script>"
    render_report(result, root / "report.html")
    html = (root / "report.html").read_text()
    assert "&lt;script&gt;" in html
    assert "<script>alert" not in html
    assert 'href="run-001/mean/trace.txt"' in html
    assert (root / "run-001/mean/trace.txt").exists()
    saved = json.loads((root / "summary.json").read_text())
    assert saved["runs"][0]["passed"] == 10


@pytest.mark.parametrize(
    "options",
    [
        dict(runs=0),
        dict(concurrency=0),
        dict(task_timeout=float("nan")),
        dict(task_timeout=-1),
        dict(usd_per_second=-1),
        dict(usd_per_second=float("inf")),
        dict(sandbox_timeout=100),
    ],
)
def test_bad_config_rejected(options):
    with pytest.raises(ValueError):
        Config(**options).validate()


def test_preflight_does_not_create_output(tmp_path):
    output = tmp_path / "missing"
    with pytest.raises(FileNotFoundError):
        run_benchmark(Config(candidates=(str(tmp_path / "no-candidate"),)), output)
    assert not output.exists()


def test_cli_export_run_report_and_exit_codes(tmp_path, monkeypatch):
    candidates = tmp_path / "candidate"
    assert main(["tasks", "--export", str(candidates), "--reference"]) == 0
    output = tmp_path / "cli"
    assert (
        main(
            [
                "run",
                "--backend",
                "local",
                "--runs",
                "1",
                "--candidates",
                str(candidates),
                "--output",
                str(output),
            ]
        )
        == 0
    )
    assert main(["report", str(output / "summary.json")]) == 0
    monkeypatch.delenv("E2B_API_KEY", raising=False)
    assert main(["run", "--runs", "1", "--output", str(tmp_path / "cloud")]) == 2
    assert not (tmp_path / "cloud").exists()


def test_incomplete_suite_cannot_pass(tmp_path):
    class EmptyBackend(FakeBackend):
        def execute(self, program, timeout):
            result = super().execute(program, timeout)
            result["tests_run"] = 0
            return result

    run = run_single(
        1,
        "reference",
        resolve_candidates(("reference",))["reference"],
        Config(),
        tmp_path,
        EmptyBackend,
        tasks=(TASKS[0],),
    )
    assert run["passed"] == 0
    assert run["tasks"][0]["status"] == "error"


def test_recovered_report_without_measured_wall_time(tmp_path):
    root = tmp_path / "recovered"
    result = run_benchmark(Config(backend="local", runs=1), root)
    result["wall_seconds"] = None
    result["recovered"] = True
    render_report(result, root / "report.html")
    html = (root / "report.html").read_text()
    assert "Recovered from saved run files" in html
    assert "<b>Unavailable</b>" in html


def test_ctrl_c_finishes_runs_and_saves_report(tmp_path, monkeypatch, capsys):
    import sandboxbench.runner as runner

    original_wait = runner.wait
    calls = 0

    def interrupt_once(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise KeyboardInterrupt
        return original_wait(*args, **kwargs)

    monkeypatch.setattr(runner, "wait", interrupt_once)
    output = tmp_path / "interrupted"
    code = main(["run", "--backend", "local", "--runs", "2", "--output", str(output)])
    assert code == 130
    saved = json.loads((output / "summary.json").read_text())
    assert saved["interrupted"] is True
    assert len(saved["runs"]) == 2
    assert all(r["passed"] == 10 for r in saved["runs"])
    assert (output / "report.html").is_file()
    stdout = capsys.readouterr().out
    assert "Finishing submitted runs" in stdout
    assert "[2/2]" in stdout
    assert "Report:" in stdout
