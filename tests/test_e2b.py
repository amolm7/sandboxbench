"""Execute the actual shipped wrapper against a mocked Code Interpreter transport."""

import io
from contextlib import redirect_stdout
from types import SimpleNamespace
from unittest.mock import Mock

from sandboxbench.backends import E2BBackend
from sandboxbench.harness import build_program
from sandboxbench.tasks import TASKS


def test_sdk_lifecycle_and_transported_wrapper(monkeypatch):
    import e2b_code_interpreter

    sandbox = Mock(sandbox_id="test-id")

    def run_code(code, **kwargs):
        output = io.StringIO()
        with redirect_stdout(output):
            exec(code, {})
        return SimpleNamespace(
            logs=SimpleNamespace(stdout=[output.getvalue()], stderr=[]), error=None
        )

    sandbox.run_code.side_effect = run_code
    create = Mock(return_value=sandbox)
    monkeypatch.setattr(e2b_code_interpreter.Sandbox, "create", create)
    backend = E2BBackend()
    try:
        backend.start(300)
        result = backend.execute(build_program(TASKS[0], TASKS[0].reference), 2)
        assert result["status"] == "passed"
        assert backend.sandbox_id == "test-id"
        create.assert_called_once_with(timeout=300, request_timeout=60)
    finally:
        backend.close()
    sandbox.kill.assert_called_once_with(request_timeout=30)


def test_code_interpreter_error_is_preserved():
    backend = E2BBackend()
    backend.sandbox = Mock()
    backend.sandbox.run_code.return_value = SimpleNamespace(
        logs=SimpleNamespace(stdout=[], stderr=["transport stderr"]),
        error=SimpleNamespace(name="Error", value="failed", traceback="trace"),
    )
    result = backend.execute("print(1)", 1)
    assert result["status"] == "error"
    assert "trace" in result["trace"]
    assert result["stderr"] == "transport stderr"
