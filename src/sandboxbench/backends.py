"""One backend instance per run. Never execute candidate code on the host by default."""

import json
from typing import Protocol


class Backend(Protocol):
    sandbox_id: str | None

    def start(self, lifetime: int) -> None: ...
    def execute(self, program: str, timeout: float) -> dict: ...
    def close(self) -> None: ...


def error_result(status: str, trace: str, stdout: str = "", stderr: str = "") -> dict:
    return dict(
        status=status, tests_run=0, failures=0, errors=0, trace=trace, stdout=stdout, stderr=stderr
    )


def run_process(program: str, timeout: float) -> dict:
    # This same function body is shipped into E2B. Keep it stdlib-only and self-contained.
    import json
    import subprocess
    import sys
    import tempfile

    try:
        with tempfile.TemporaryDirectory(prefix="sandboxbench-") as cwd:
            completed = subprocess.run(
                [sys.executable, "-I", "-c", program],
                cwd=cwd,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        if completed.returncode:
            return dict(
                status="error",
                tests_run=0,
                failures=0,
                errors=0,
                stdout=completed.stdout,
                stderr=completed.stderr,
                trace=f"Test process exited {completed.returncode}",
            )
        result = json.loads(completed.stdout)
        required = {"status", "tests_run", "failures", "errors", "trace", "stdout", "stderr"}
        if not isinstance(result, dict) or not required <= result.keys():
            raise ValueError("Invalid test process result")
        return result
    except subprocess.TimeoutExpired as exc:

        def decode(value):
            return value.decode(errors="replace") if isinstance(value, bytes) else value or ""

        return dict(
            status="timeout",
            tests_run=0,
            failures=0,
            errors=0,
            stdout=decode(exc.stdout),
            stderr=decode(exc.stderr),
            trace=f"Task exceeded {timeout}s subprocess deadline",
        )


class LocalBackend:
    """Development only: subprocesses are NOT a security boundary."""

    sandbox_id = None

    def start(self, lifetime: int) -> None:
        pass

    def execute(self, program: str, timeout: float) -> dict:
        return run_process(program, timeout)

    def close(self) -> None:
        pass


class E2BBackend:
    sandbox_id = None

    def __init__(self) -> None:
        self.sandbox = None

    def start(self, lifetime: int) -> None:
        from e2b_code_interpreter import Sandbox

        self.sandbox = Sandbox.create(timeout=lifetime, request_timeout=60)
        self.sandbox_id = self.sandbox.sandbox_id

    def execute(self, program: str, timeout: float) -> dict:
        import inspect
        import uuid

        marker = "SANDBOXBENCH_" + uuid.uuid4().hex + ":"
        wrapper = (
            "import json\n"
            + inspect.getsource(run_process)
            + f"\nprint({marker!r} + json.dumps(run_process({program!r}, {timeout!r})))\n"
        )
        execution = self.sandbox.run_code(
            wrapper,
            timeout=timeout + 10,
            request_timeout=timeout + 20,
        )
        stdout = "".join(execution.logs.stdout)
        stderr = "".join(execution.logs.stderr)
        if execution.error:
            error = execution.error
            return error_result(
                "error", f"{error.name}: {error.value}\n{error.traceback}", stdout, stderr
            )
        for line in reversed(stdout.splitlines()):
            if line.startswith(marker):
                result = json.loads(line[len(marker) :])
                result["transport_stdout"] = stdout[: stdout.rfind(marker)]
                result["transport_stderr"] = stderr
                return result
        return error_result("error", "E2B returned no structured test result", stdout, stderr)

    def close(self) -> None:
        if self.sandbox is not None:
            self.sandbox.kill(request_timeout=30)
