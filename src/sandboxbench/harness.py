"""Build a standalone stdlib-only unit-test program, identical on local and E2B."""

from .tasks import Task


def build_program(task: Task, candidate: str) -> str:
    methods = []
    for index, check in enumerate(task.checks):
        body = "\n".join("        " + line for line in check.splitlines())
        methods.append(f"    def test_{index:03d}(self):\n{body}\n")
    tests = "class Checks(unittest.TestCase):\n" + "\n".join(methods)
    # Candidate stdout never shares the JSON protocol stream. Tests execute in a fresh process.
    return f"""
import contextlib
import io
import json
import traceback
import unittest

captured_out, captured_err, trace = io.StringIO(), io.StringIO(), io.StringIO()
namespace = {{"__name__": "candidate", "unittest": unittest}}
result = {{"status": "error", "tests_run": 0, "failures": 0, "errors": 0}}
with contextlib.redirect_stdout(captured_out), contextlib.redirect_stderr(captured_err):
    try:
        exec(compile({candidate!r}, "candidate.py", "exec"), namespace)
        exec(compile({tests!r}, "checks.py", "exec"), namespace)
        suite = unittest.defaultTestLoader.loadTestsFromTestCase(namespace["Checks"])
        checked = unittest.TextTestRunner(stream=trace, verbosity=2).run(suite)
        complete = checked.wasSuccessful() and not checked.skipped and not checked.expectedFailures
        result.update(status="passed" if complete else "failed",
                      tests_run=checked.testsRun, failures=len(checked.failures),
                      errors=len(checked.errors))
    except BaseException:
        traceback.print_exc(file=trace)
result.update(stdout=captured_out.getvalue(), stderr=captured_err.getvalue(),
              trace=trace.getvalue())
print(json.dumps(result))
"""
