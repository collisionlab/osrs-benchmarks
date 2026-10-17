"""Compare two run directories: per-scenario speed and any change in what the scenarios found."""
import math
import statistics
from collections import defaultdict

from .run import load

# Changes smaller than this are within the run-to-run noise of a desktop runner.
THRESHOLD = 0.10


def by_case(observations):
    """{(backend, scenario suite, scenario): (median total_ns or None, outcomes, path costs)}"""
    grouped = defaultdict(list)
    for row in observations:
        grouped[(row["backend"], row["scenario_suite"], row["scenario"])].append(row)
    result = {}
    for key, rows in grouped.items():
        times = [r["total_ns"] for r in rows if r["outcome"] != "failed"]
        result[key] = (statistics.median(times) if times else None,
                       sorted({r["outcome"] for r in rows}),
                       sorted({r["path_cost"] for r in rows}, key=lambda c: (c is None, c)))
    return result


def summarise(keys, base, cand):
    """(ratios, changed) over keys: time ratios of cases both runs timed, and result changes."""
    ratios, changed = [], []
    for key in keys:
        (bt, bo, bc), (ct, co, cc) = base[key], cand[key]
        if (bo, bc) != (co, cc):
            changed.append((key, bo, bc, co, cc))
        if bt and ct:
            ratios.append((ct / bt, key, bt, ct))
    return ratios, changed


def row(label, keys, ratios, changed):
    geomean = math.exp(sum(math.log(r) for r, *_ in ratios) / len(ratios)) if ratios else float("nan")
    faster = sum(1 for r, *_ in ratios if r < 1 - THRESHOLD)
    slower = sum(1 for r, *_ in ratios if r > 1 + THRESHOLD)
    return f"| {label} | {len(keys)} | {percent(geomean)} | {faster} | {slower} | {len(changed)} |"


def describe_run(run):
    label = f", {run['label']}" if run.get("label") else ""
    return (f"tooling `{run['tooling_commit'][:12]}`, plugin `{run['plugin_commit'][:12]}` "
            f"({run['suite']}, {run['runner']}, {run.get('trigger', '')}{label})")


def compare(baseline_dir, candidate_dir, top=10):
    """A Markdown report."""
    base_run, _, base_rows = load(baseline_dir)
    cand_run, _, cand_rows = load(candidate_dir)
    base, cand = by_case(base_rows), by_case(cand_rows)
    lines = [f"Baseline: {describe_run(base_run)}", f"Candidate: {describe_run(cand_run)}", ""]
    if base_run["suite_sha256"] != cand_run["suite_sha256"]:
        lines += ["The runs used different suite definitions, so only shared scenarios are compared.", ""]
    differences = [f"{field} {base_run.get(field)} vs {cand_run.get(field)}"
                   for field in ("runner", "cpu_governor", "cpu_boost", "kernel")
                   if base_run.get(field) != cand_run.get(field)]
    if differences:
        lines += [f"The machines differed ({'; '.join(differences)}), so times are not comparable.", ""]
    header = ["| {} | scenarios | geomean time | faster >10% | slower >10% | result changes |",
              "|---|---:|---:|---:|---:|---:|"]
    shared = base.keys() & cand.keys()
    lines += [header[0].format("backend"), header[1]]
    details = []
    for backend in sorted({k[0] for k in shared}):
        keys = sorted(k for k in shared if k[0] == backend)
        ratios, changed = summarise(keys, base, cand)
        lines.append(row(backend, keys, ratios, changed))
        per_suite = ["", f"By suite ({backend}):", "", header[0].format("suite"), header[1]]
        for suite in sorted({k[1] for k in keys}):
            suite_keys = [k for k in keys if k[1] == suite]
            per_suite.append(row(suite, suite_keys, *summarise(suite_keys, base, cand)))
        details += per_suite
        worst = sorted(ratios, reverse=True)[:top]
        if worst:
            details += ["", f"Slowest changes ({backend}):", "", "| suite | scenario | baseline | candidate | change |",
                        "|---|---|---:|---:|---:|"]
            details += [f"| {k[1]} | {k[2]} | {ms(bt)} | {ms(ct)} | {percent(r)} |" for r, k, bt, ct in worst]
        if changed:
            details += ["", f"Result changes ({backend}):", "", "| suite | scenario | baseline | candidate |",
                        "|---|---|---|---|"]
            details += [f"| {k[1]} | {k[2]} | {describe(bo, bc)} | {describe(co, cc)} |"
                        for k, bo, bc, co, cc in changed]
    return "\n".join(lines + details) + "\n"


def percent(ratio):
    return "n/a" if math.isnan(ratio) else f"{(ratio - 1) * 100:+.1f}%"


def ms(ns):
    return f"{ns / 1e6:.2f} ms"


def describe(outcomes, costs):
    return f"{'/'.join(outcomes)}, cost {'/'.join('none' if c is None else str(c) for c in costs)}"
