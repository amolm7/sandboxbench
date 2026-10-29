"""CLI with cloud preflight before any sandbox is created."""

import argparse
import importlib.util
import json
import os
import sys
import uuid
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from .report import render_report
from .runner import Config, run_benchmark
from .tasks import TASKS


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description="Synthetic coding-task benchmarks on E2B")
    commands = root.add_subparsers(dest="command", required=True)
    tasks = commands.add_parser("tasks", help="List specs, or export candidate files")
    tasks.add_argument("--export", type=Path)
    tasks.add_argument(
        "--reference", action="store_true", help="Export solutions instead of starters"
    )
    run = commands.add_parser("run", help="Execute the complete suite per sandbox")
    run.add_argument("--backend", choices=["e2b", "local"], default="e2b")
    run.add_argument("--runs", type=int, default=20)
    run.add_argument("--concurrency", type=int, default=20)
    run.add_argument(
        "--candidates",
        nargs="+",
        default=["reference"],
        help="reference, baseline, or directories of <task-id>.py; assigned round-robin",
    )
    run.add_argument("--task-timeout", type=float, default=5)
    run.add_argument("--sandbox-timeout", type=int, default=300)
    run.add_argument(
        "--usd-per-second",
        type=float,
        default=0,
        help="Total sandbox compute rate; 0 marks estimates as unset",
    )
    run.add_argument("--output", type=Path, help="New artifact directory (must not exist)")
    report = commands.add_parser("report", help="Regenerate HTML beside an existing summary.json")
    report.add_argument("summary", type=Path)
    return root


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        if args.command == "tasks":
            if args.export:
                args.export.mkdir(parents=True, exist_ok=False)
                for task in TASKS:
                    source = task.reference if args.reference else task.starter
                    (args.export / f"{task.id}.py").write_text(source, encoding="utf-8")
                (args.export / "specs.json").write_text(
                    json.dumps([asdict(t) for t in TASKS], indent=2) + "\n",
                    encoding="utf-8",
                )
            else:
                for task in TASKS:
                    print(f"{task.id:18} [{task.category}] {task.spec}")
            return 0
        if args.command == "report":
            manifest = json.loads(args.summary.read_text(encoding="utf-8"))
            destination = args.summary.parent / "report.html"
            render_report(manifest, destination)
            print(destination.resolve())
            return 0
        config = Config(
            backend=args.backend,
            runs=args.runs,
            concurrency=args.concurrency,
            candidates=tuple(args.candidates),
            task_timeout=args.task_timeout,
            sandbox_timeout=args.sandbox_timeout,
            usd_per_second=args.usd_per_second,
        )
        config.validate()
        if config.backend == "e2b":
            if not os.environ.get("E2B_API_KEY"):
                raise ValueError("Set E2B_API_KEY, or use --backend local with trusted code")
            if importlib.util.find_spec("e2b_code_interpreter") is None:
                raise ValueError("Install the E2B SDK: pip install -e .")
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        output = args.output or Path("results") / f"{stamp}-{uuid.uuid4().hex[:8]}"
        print(
            f"Running {config.runs} suites on {config.backend} "
            f"(up to {min(config.runs, config.concurrency)} concurrent)",
            flush=True,
        )
        manifest = run_benchmark(config, output, on_progress=lambda text: print(text, flush=True))
        render_report(manifest, output / "report.html")
        passed = sum(run["passed"] for run in manifest["runs"])
        total = sum(run["total"] for run in manifest["runs"])
        print(f"{passed}/{total} tasks passed. Report: {(output / 'report.html').resolve()}")
        if manifest.get("interrupted"):
            return 130
        operational_error = any(
            r["status"] == "error" or any(t["status"] in {"error", "timeout"} for t in r["tasks"])
            for r in manifest["runs"]
        )
        return 2 if operational_error else (0 if passed == total else 1)
    except KeyboardInterrupt:
        print(
            "sandboxbench: interrupted; completed run files remain in the output directory.",
            file=sys.stderr,
        )
        return 130
    except (ValueError, OSError, ImportError) as exc:
        print(f"sandboxbench: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
