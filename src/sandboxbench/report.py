"""Offline HTML with escaped traces and relative artifact links."""

from collections import defaultdict
from html import escape
from pathlib import Path
from statistics import median

STYLE = """
:root{color-scheme:dark;font-family:system-ui,sans-serif;background:#10151f;color:#e5eaf2}
body{max-width:1200px;margin:auto;padding:40px 24px}h1{font-size:42px;margin:8px 0}
h2{margin-top:36px}p,small{color:#aebbd0}a{color:#81ceff}table{width:100%;border-collapse:collapse}
th,td{text-align:left;padding:12px;border-bottom:1px solid #303b50;font-variant-numeric:tabular-nums}
th{color:#aebbd0;font-size:12px;text-transform:uppercase}.cards{display:flex;gap:16px;flex-wrap:wrap}
.card{background:#1b2433;border:1px solid #303b50;padding:20px;border-radius:12px;flex:1;min-width:140px}
.card b{display:block;font-size:28px}.passed{color:#77e5b4}.failed,.error,.timeout{color:#ffb199}
progress{width:100px;accent-color:#77e5b4}details{border:1px solid #303b50;padding:14px;border-radius:8px;
margin:12px 0}summary{cursor:pointer}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#0b1018;
padding:16px;max-height:360px;overflow:auto}.scroll{overflow-x:auto}label{display:block;margin:20px 0}
select{padding:8px;background:#1b2433;color:#e5eaf2;border:1px solid #506078;border-radius:6px}
"""


def render_report(manifest: dict, destination: Path) -> None:
    runs = manifest["runs"]
    groups = defaultdict(list)
    for run in runs:
        groups[run["candidate"]].append(run)
    total = sum(r["total"] for r in runs)
    passed = sum(r["passed"] for r in runs)
    cost = sum(r["estimated_cost_usd"] for r in runs)
    config = manifest["config"]
    cohorts = []
    for name, members in groups.items():
        rate = sum(r["passed"] for r in members) / sum(r["total"] for r in members)
        times = [t["seconds"] for r in members for t in r["tasks"]]
        task_time = f"{median(times):.3f}s" if times else "—"
        cohorts.append(
            f"<tr><td>{escape(name)}</td><td>{len(members)}</td><td>{rate:.1%} "
            f'<progress max="1" value="{rate}"></progress></td><td>{task_time}</td>'
            f"<td>{median(r['seconds'] for r in members):.2f}s</td>"
            f"<td>${sum(r['estimated_cost_usd'] for r in members):.6f}</td></tr>"
        )
    rows, details = [], []
    for run in runs:
        rid = escape(run["id"])
        operational = bool(run["error"] or run["cleanup_error"]) or any(
            t["status"] in {"error", "timeout"} for t in run["tasks"]
        )
        status = (
            "error" if operational else ("passed" if run["passed"] == run["total"] else "failed")
        )
        startup = run["startup_seconds"]
        startup_text = f"{startup:.3f}s" if startup is not None else "—"
        rows.append(
            f'<tr data-status="{status}"><td><a href="#{rid}">{rid}</a></td>'
            f"<td>{escape(run['candidate'])}</td><td>{run['passed']}/{run['total']}</td>"
            f"<td>{startup_text}</td><td>{run['seconds']:.3f}s</td>"
            f"<td>${run['estimated_cost_usd']:.6f}</td><td class='{status}'>{status}</td></tr>"
        )
        task_rows = []
        for task in run["tasks"]:
            tid = escape(task["task_id"])
            base = f"{rid}/{tid}"
            links = " · ".join(
                f'<a href="{base}/{file}">{label}</a>'
                for file, label in [
                    ("result.json", "Result JSON"),
                    ("candidate.py", "Code"),
                    ("harness.py", "Harness"),
                    ("stdout.txt", "stdout"),
                    ("stderr.txt", "stderr"),
                    ("trace.txt", "Trace"),
                ]
            )
            task_rows.append(
                f"<details><summary><span class='{escape(task['status'])}'>"
                f"{escape(task['status']).upper()}</span> · {tid} · {task['seconds']:.3f}s · "
                f"{task['tests_run']}/{task['expected_tests']} checks executed</summary>"
                f"<p>{links}</p><pre>{escape(task['trace'])}</pre></details>"
            )
        errors = "\n".join(e for e in [run["error"], run["cleanup_error"]] if e)
        details.append(
            f'<details id="{rid}"><summary>{rid} · {escape(run["candidate"])} · '
            f"{run['passed']}/{run['total']} tasks passed</summary>"
            f"<p>Sandbox: {escape(run['sandbox_id'] or 'local / unavailable')}</p>"
            + (f"<pre>{escape(errors)}</pre>" if errors else "")
            + "".join(task_rows)
            + "</details>"
        )
    note = (
        "Cost rate is unset: $0 values are placeholders, not a free-service claim."
        if not config["usd_per_second"]
        else f"Estimated compute at ${config['usd_per_second']:.8f}/sandbox-second; not an invoice."
    )
    if config["backend"] == "local":
        note = "LOCAL DEVELOPMENT RUN · no cloud cost or E2B latency was measured."
    wall_time = manifest["wall_seconds"]
    wall_text = f"{wall_time:.2f}s" if wall_time is not None else "Unavailable"
    recovery_note = (
        "<p>Recovered from saved run files. Total wall time was not recorded.</p>"
        if manifest.get("recovered")
        else ""
    )
    html = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<title>SandboxBench report</title><style>{STYLE}</style></head><body>
<small>SANDBOXBENCH / SUITE {escape(manifest["suite_version"])}</small>
<h1>Coding tasks, measured.</h1>
<p>{escape(manifest["created_at"])} · {escape(config["backend"])} ·
{len(runs)} runs · concurrency {config["concurrency"]}</p>
<div class="cards"><div class="card"><small>Task pass rate</small><b>{passed / total:.1%}</b>
{passed}/{total} scheduled tasks</div><div class="card"><small>Wall time</small>
<b>{wall_text}</b>Including concurrent startup and cleanup</div>
<div class="card"><small>Estimated compute cost</small><b>${cost:.6f}</b>Across all runs</div></div>
{recovery_note}
<p>{escape(note)} Failed create/cleanup uses at least the configured TTL as its cost basis.</p>
<h2>Candidate comparison</h2><div class="scroll"><table><thead><tr><th>Candidate</th><th>Runs</th>
<th>Task pass rate</th><th>Median task latency</th><th>Median run latency</th><th>Total est. cost</th>
</tr></thead><tbody>{"".join(cohorts)}</tbody></table></div>
<h2>Runs</h2><label>Show <select id="filter"><option value="all">All runs</option>
<option value="passed">Passed</option><option value="failed">Failed checks</option>
<option value="error">Execution / infrastructure errors</option></select></label>
<div class="scroll"><table><thead><tr><th>Run</th><th>Candidate</th><th>Tasks passed</th>
<th>Startup</th><th>End-to-end</th><th>Est. cost</th><th>Status</th></tr></thead>
<tbody>{"".join(rows)}</tbody></table></div>
<h2>Task traces</h2>{"".join(details)}
<p>Pass requires every check. Unexecuted tasks count against the pass rate. Task latency includes
transport and test-process overhead; startup and cleanup are included in run latency.
Synthetic reference/baseline results do not measure an LLM's coding ability.</p>
<p><a href="summary.json">Full machine-readable results</a> · <a href="config.json">Configuration</a></p>
<script>document.getElementById('filter').addEventListener('change',e=>{{
document.querySelectorAll('tr[data-status]').forEach(r=>{{
r.hidden=e.target.value!=='all'&&r.dataset.status!==e.target.value;}});}});</script>
</body></html>"""
    destination.write_text(html, encoding="utf-8")
