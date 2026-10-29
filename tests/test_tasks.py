import pytest

from sandboxbench.backends import LocalBackend
from sandboxbench.harness import build_program
from sandboxbench.tasks import TASKS


@pytest.mark.parametrize("task", TASKS, ids=lambda t: t.id)
def test_reference_passes_and_starter_fails(task):
    backend = LocalBackend()
    result = backend.execute(build_program(task, task.reference), 3)
    assert result["status"] == "passed", result["trace"]
    assert result["tests_run"] == len(task.checks)
    baseline = backend.execute(build_program(task, task.starter), 3)
    assert baseline["status"] == "failed", baseline["trace"]


def test_timeout_and_syntax_errors():
    backend = LocalBackend()
    result = backend.execute(build_program(TASKS[0], "while True: pass"), 0.1)
    assert result["status"] == "timeout"
    result = backend.execute(build_program(TASKS[0], "def broken(:"), 1)
    assert result["status"] == "error"
    assert "SyntaxError" in result["trace"]


def test_candidate_output_is_captured():
    task = TASKS[0]
    source = "import sys\nprint('hello')\nprint('warning', file=sys.stderr)\n" + task.reference
    result = LocalBackend().execute(build_program(task, source), 1)
    assert result["status"] == "passed"
    assert result["stdout"] == "hello\n"
    assert result["stderr"] == "warning\n"


def test_skipped_checks_cannot_pass():
    source = "import unittest\ndef mean(values):\n    raise unittest.SkipTest('not implemented')\n"
    result = LocalBackend().execute(build_program(TASKS[0], source), 1)
    assert result["tests_run"] == len(TASKS[0].checks)
    assert result["status"] == "failed"
