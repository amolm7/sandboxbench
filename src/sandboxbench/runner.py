"""Single-sandbox lifecycle first; bounded thread orchestration wraps that same runner."""

import hashlib
import json
import math
import time
import traceback
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from .backends import Backend, E2BBackend, LocalBackend, error_result
from .harness import build_program
from .tasks import SUITE_VERSION, TASKS, Task


@dataclass(frozen=True)
class Config:
    backend: str = "e2b"
    runs: int = 20
    concurrency: int = 20
    candidates: tuple[str, ...] = ("reference",)
    task_timeout: float = 5.0
    sandbox_timeout: int = 300
    usd_per_second: float = 0.0

    def validate(self) -> None:
        if self.backend not in {"local", "e2b"}:
            raise ValueError("backend must be local or e2b")
        if self.runs < 1 or self.concurrency < 1:
            raise ValueError("runs and concurrency must be positive")
        if not self.candidates:
            raise ValueError("at least one candidate is required")
        if not math.isfinite(self.task_timeout) or self.task_timeout <= 0:
            raise ValueError("task timeout must be finite and positive")
        if self.sandbox_timeout <= len(TASKS) * (self.task_timeout + 20) + 30:
            raise ValueError("sandbox timeout must exceed 10 * (task timeout + 20) + 30 seconds")
        if not math.isfinite(self.usd_per_second) or self.usd_per_second < 0:
            raise ValueError("USD rate must be finite and nonnegative")


def write_json(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def resolve_candidates(names: tuple[str, ...]) -> dict[str, dict[str, str]]:
    """Snapshot all files before launching any billable sandbox."""
    resolved = {}
    for name in names:
        if name in {"reference", "baseline"}:
            resolved[name] = {
                t.id: t.reference if name == "reference" else t.starter for t in TASKS
            }
        else:
            root = Path(name)
            resolved[name] = {
                t.id: (root / f"{t.id}.py").read_text(encoding="utf-8") for t in TASKS
            }
    return resolved


def run_single(
    index: int,
    candidate: str,
    sources: dict[str, str],
    config: Config,
    root: Path,
    backend_factory: Callable[[], Backend],
    tasks: tuple[Task, ...] = TASKS,
) -> dict:
    run_id = f"run-{index:03d}"
    folder = root / run_id
    folder.mkdir()
    backend = backend_factory()
    started = time.perf_counter()
    run = dict(
        id=run_id,
        candidate=candidate,
        sandbox_id=None,
        status="completed",
        tasks=[],
        startup_seconds=None,
        cleanup_error=None,
        error=None,
    )
    lifetime_started = started
    try:
        backend.start(config.sandbox_timeout)
        run["sandbox_id"] = backend.sandbox_id
        run["startup_seconds"] = time.perf_counter() - started
        for task in tasks:
            task_dir = folder / task.id
            task_dir.mkdir()
            source = sources[task.id]
            program = build_program(task, source)
            (task_dir / "candidate.py").write_text(source, encoding="utf-8")
            (task_dir / "harness.py").write_text(program, encoding="utf-8")
            write_json(task_dir / "task.json", asdict(task))
            tick = time.perf_counter()
            try:
                result = backend.execute(program, config.task_timeout)
            except Exception:
                result = error_result("error", traceback.format_exc())
            result.update(
                task_id=task.id,
                category=task.category,
                expected_tests=len(task.checks),
                seconds=time.perf_counter() - tick,
                source_sha256=hashlib.sha256(source.encode()).hexdigest(),
                artifact=f"{run_id}/{task.id}/result.json",
            )
            # Incomplete/empty/skipped suites must never be counted as a task pass.
            if result["status"] == "passed" and result["tests_run"] != len(task.checks):
                result["status"] = "error"
                result["trace"] += "\nIncomplete test suite"
            write_json(task_dir / "result.json", result)
            (task_dir / "trace.txt").write_text(result["trace"], encoding="utf-8")
            (task_dir / "stdout.txt").write_text(result["stdout"], encoding="utf-8")
            (task_dir / "stderr.txt").write_text(result["stderr"], encoding="utf-8")
            run["tasks"].append(result)
    except Exception:
        run["status"] = "error"
        run["error"] = traceback.format_exc()
    finally:
        try:
            backend.close()
        except Exception:
            run["cleanup_error"] = traceback.format_exc()
            run["status"] = "error"
        run["seconds"] = time.perf_counter() - started
        run["lifetime_seconds"] = time.perf_counter() - lifetime_started
        # On a failed create/kill, budget for the entire configured TTL. This remains an estimate.
        uncertain = run["startup_seconds"] is None or run["cleanup_error"] is not None
        run["cost_basis_seconds"] = (
            (
                max(run["lifetime_seconds"], config.sandbox_timeout)
                if uncertain
                else run["lifetime_seconds"]
            )
            if config.backend == "e2b"
            else 0.0
        )
        run["estimated_cost_usd"] = run["cost_basis_seconds"] * config.usd_per_second
        run["cost_uncertain"] = uncertain and config.backend == "e2b"
        run["passed"] = sum(t["status"] == "passed" for t in run["tasks"])
        run["total"] = len(tasks)
        run["pass_rate"] = run["passed"] / len(tasks)
        write_json(folder / "run.json", run)
    return run


def run_benchmark(
    config: Config,
    root: Path,
    backend_factory: Callable[[], Backend] | None = None,
    on_progress: Callable[[str], None] | None = None,
) -> dict:
    config.validate()
    sources = resolve_candidates(config.candidates)
    root.mkdir(parents=True, exist_ok=False)
    write_json(root / "config.json", asdict(config))
    factory = backend_factory or (E2BBackend if config.backend == "e2b" else LocalBackend)
    started = time.perf_counter()
    results = []
    interrupted = False
    last_update = started
    with ThreadPoolExecutor(max_workers=min(config.concurrency, config.runs)) as pool:
        futures = []
        for i in range(config.runs):
            name = config.candidates[i % len(config.candidates)]
            futures.append(
                pool.submit(run_single, i + 1, name, sources[name], config, root, factory)
            )
        pending = set(futures)
        while pending:
            try:
                done, pending = wait(pending, timeout=1, return_when=FIRST_COMPLETED)
            except KeyboardInterrupt:
                if interrupted:
                    raise
                interrupted = True
                if on_progress:
                    on_progress(
                        "Interrupted. Finishing submitted runs, cleaning up sandboxes, and saving "
                        "the report. Press Ctrl+C again to abandon report generation."
                    )
                continue
            for future in done:
                run = future.result()
                results.append(run)
                if on_progress:
                    on_progress(
                        f"[{len(results)}/{config.runs}] {run['id']}: "
                        f"{run['passed']}/{run['total']} tasks passed ({run['seconds']:.2f}s)"
                    )
            now = time.perf_counter()
            if pending and now - last_update >= 5:
                if on_progress:
                    on_progress(f"Waiting for {len(pending)} runs ({now - started:.0f}s elapsed)")
                last_update = now
    results.sort(key=lambda run: run["id"])
    manifest = dict(
        schema_version=1,
        interrupted=interrupted,
        suite_version=SUITE_VERSION,
        created_at=datetime.now(timezone.utc).isoformat(),
        config=asdict(config),
        wall_seconds=time.perf_counter() - started,
        runs=results,
    )
    write_json(root / "summary.json", manifest)
    return manifest
