# SandboxBench

A Python benchmark harness for synthetic coding-agent tasks on [E2B](https://e2b.dev).
Run **20 independent sandboxes concurrently**, execute the same 10 tasks in each,
and open an offline HTML report comparing pass rate, latency, and estimated compute cost.
Every task keeps its candidate source, executable harness, stdout, stderr, and unit-test trace.

This project measures execution of supplied code. It ships reference solutions and flawed
starters so you can verify the harness without buying LLM tokens. It does **not** call an agent
or claim to measure model quality. An agent can generate the candidate files described below.

## Quick start

Requires Python 3.11+ and an E2B account for cloud execution.

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'

# First: a single local run of trusted reference solutions (no API key).
sandboxbench run --backend local --runs 1 --concurrency 1 --output results/single
# Open results/single/report.html in your browser.

# Then: a single real E2B sandbox.
export E2B_API_KEY='your-key'
sandboxbench run --runs 1 --concurrency 1 --output results/cloud-single

# Finally: 20 sandboxes, each executing all 10 tasks = 200 task attempts.
sandboxbench run --runs 20 --concurrency 20 --output results/cloud-20
```

`E2B_API_KEY` is read by the SDK from the environment, never written into the run config.
`.env.example` documents the variable; `.env` files are not loaded automatically.
E2B execution incurs account charges. Account concurrency quotas may require lowering
`--concurrency`; requested concurrency is a maximum, not a guarantee of simultaneous startup.
A missing key or missing candidate file fails preflight before creating sandboxes.
Existing output directories are rejected to preserve prior artifacts.
The terminal prints completed-run counts and a waiting update every five seconds.
One Ctrl+C lets submitted runs finish, cleans up sandboxes, saves the report, and returns
exit code 130. A second Ctrl+C abandons report generation and can leave only per-run artifacts.
Python may still wait for worker threads; sandbox TTL remains the fallback for cleanup. Finishing submitted runs can still incur charges.

For an offline comparison of known passing and failing candidates:

```bash
sandboxbench run --backend local --runs 20 --concurrency 20 \
  --candidates reference baseline --output results/comparison
# Expected: 100/200 tasks pass; exit code 1 because baselines deliberately fail.
```

The local backend executes Python subprocesses **on your machine** and is only for trusted code.
It is not a sandbox or an accurate proxy for E2B performance.

## Architecture

```text
CLI + configuration + candidate snapshot
                  |
        bounded ThreadPoolExecutor (20 workers by default)
                  |
        run_single() — one backend/sandbox per run
                  |
        create → task 1 → ... → task 10 → kill in finally
                     |
           Code Interpreter run_code()
                     |
        fresh Python subprocess + unittest checks
                     |
       JSON result + stdout/stderr + test traceback
                  |
       summary.json → self-contained report.html
```

The implementation is layered: task suite and test harness first, a single-sandbox lifecycle
next, and parallel execution as a thin coordinator around the same `run_single()` function.
Threads suit the synchronous SDK's network calls and keep sandbox ownership simple.
Tasks are sequential within a sandbox; runs execute concurrently. Every task gets a fresh
Python process and temporary working directory, so notebook variables do not bleed across tasks.
Tasks within a run still share the sandbox filesystem and OS; this is process isolation,
not a separate security boundary between tasks. All tasks use the Python standard library.

The E2B adapter uses [`Sandbox.create`, `run_code`](https://docs.e2b.dev/quickstart)
and `kill()` with explicit request deadlines.
The subprocess deadline is 5 seconds by default; the outer SDK call gets a 10-second margin.
The default sandbox TTL is 300 seconds. Configuration requires TTL to exceed the sum of
per-task execution/transport budgets plus cleanup margin. Each lifecycle attempts cleanup
in `finally`, including when execution fails. A failed cleanup is visible in the report;
TTL remains the fallback if the client cannot reach a sandbox. Abrupt host termination cannot
promise cleanup. There are no automatic retries, avoiding hidden duplicate execution and cost.

## Task suite v1.0.0

| ID | Category | Checks |
| --- | --- | --- |
| `mean` | Bug fix | Fractional means, negatives, empty input |
| `chunk` | Implementation | Partial chunks, empty input, invalid sizes |
| `deduplicate` | Refactor | Stable order, no input mutation |
| `balanced` | Bug fix | Bracket nesting and premature closing |
| `merge_intervals` | Implementation | Touching/nested intervals, sorted output, no mutation |
| `word_counts` | Refactor | Case folding, punctuation, digits |
| `binary_search` | Bug fix | Missing targets, duplicates, empty input |
| `flatten` | Implementation | Nested lists; atomic strings, tuples, and None |
| `rotate` | Bug fix | Large and negative rotations, empty input, copying |
| `group_records` | Refactor | Repeated/missing keys, stable grouping, no mutation |

There are **43 unit tests** across 10 tasks. A task passes only if all its checks run and pass.
The shipped reference candidate passes all 10 tasks; every baseline task fails at least one check.
Tests verify behavior, not algorithmic complexity or refactoring style. This small public suite
is a smoke benchmark, not a comprehensive coding evaluation. Candidate code and checks share
a process, so the grader assumes cooperative submissions and is not tamper resistant.

## Supply agent-generated candidates

```bash
sandboxbench tasks
sandboxbench tasks --export candidates/my-agent
# Give your agent the specs; replace each <task-id>.py with its proposed implementation.
# specs.json also includes public checks and reference code for harness development.
# For an agent experiment, construct prompts from id/category/spec/starter only.
sandboxbench run --candidates candidates/my-agent --runs 20 --concurrency 20

# Compare two saved candidate sets; each gets 10 of the 20 runs, round-robin.
sandboxbench run --candidates candidates/agent-a candidates/agent-b --runs 20
```

Each candidate directory must contain all 10 `<task-id>.py` files and use the specified function
names. The coordinator reads and snapshots all sources before startup, making concurrent runs
use identical code even if you edit files later. SHA-256 hashes are recorded per task.
Candidate sets represent already generated answers; per-task execution traces are not LLM
reasoning traces. A future agent adapter can supply files and save its own tool-call logs.

## Metrics and artifacts

- **Task pass rate:** passed tasks / all scheduled tasks. Failed startup counts as 0/10;
  execution errors and timeouts never shrink the denominator.
- **Task latency:** host-observed execution round trip including subprocess and test overhead.
  Median task latency includes successful, failed, and timed-out attempts that actually ran.
- **Startup:** `create()` round trip. **Run latency:** startup through cleanup. **Wall time:**
  concurrent execution overall; it is not the sum of run durations.
- **Cost estimate:** sum of measured per-sandbox lifetimes × your supplied total sandbox rate.
  Failed create/kill uses at least the full configured TTL as a conservative cost basis.
  Startup is included, making this a rough estimate rather than billing telemetry. Local cost is 0.

Set the total rate for your sandbox's resource configuration using `--usd-per-second`.
The default of 0 is explicitly labeled **unset** in cloud reports. Consult your account's
[E2B pricing](https://e2b.dev/pricing); no changing price is hard-coded. The estimate excludes
LLM tokens, paid plans, storage/network charges, billing granularity, and resource changes.

```text
results/<timestamp>-<unique-id>/
├── config.json                 # No API key
├── summary.json                # Schema version, suite version, complete run results
├── report.html                 # Offline report; filter runs and expand test traces
└── run-001/                    # Repeated for every run
    ├── run.json                # Timing, sandbox ID, cost basis, lifecycle errors
    └── mean/                   # Repeated for every task
        ├── task.json           # Exact task definition and public checks
        ├── candidate.py
        ├── harness.py          # Re-executable unit-test program
        ├── result.json         # Counts, status, duration, source hash, logs
        ├── stdout.txt
        ├── stderr.txt
        └── trace.txt
```

The report compares candidate cohorts and individual runs, with per-task artifact links.
HTML content is escaped and report assets need no CDN. Keep the entire output directory
when sharing it so the relative links work. Logs may contain whatever candidates print.
JSON is the source of truth; rebuild HTML with:

```bash
sandboxbench report results/single/summary.json
```

CLI exit codes: **0** all tasks passed, **1** assertion/test failures, **2** configuration,
execution/timeout, or infrastructure errors. A comparison containing the deliberate baseline
normally returns 1. Use a reference-only run as the CI smoke check.

## Development

```bash
pytest -q
ruff check .
```

Tests exercise all reference/baseline pairs, timeout and syntax failures, stdout capture,
actual overlapping runs with bounded workers, cleanup failures, full-denominator scoring,
CLI preflight, artifact persistence, HTML escaping, and the transported E2B harness with a
mocked SDK boundary. CI runs on Python 3.11–3.13 without cloud credentials. The local development environment was verified with E2B Code Interpreter SDK 2.11.6. Mocked tests do
not replace a real E2B integration run; run the single-sandbox cloud command to validate your
account and deployment environment.

```text
src/sandboxbench/
  tasks.py       Versioned specs, starters, reference solutions, unit-test checks
  harness.py     Standalone unittest program generation
  backends.py    E2B Code Interpreter adapter + local subprocess development backend
  runner.py      Configuration, candidate snapshots, single lifecycle, thread coordinator
  report.py      Escaped offline HTML with candidate/run comparisons
  cli.py         tasks / run / report commands
```

Potential next steps: agent-provider adapters, hidden held-out tasks, multi-language execution,
p95 latency distributions, repeated trials across regions/templates, and observed billing data.
Keep those experiments separate from the deterministic reference benchmark so results remain
interpretable.

## License

MIT. See [LICENSE](LICENSE).
