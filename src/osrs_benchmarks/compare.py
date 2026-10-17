"""Compare two run directories: per-case speed and any change in what the routes found."""
import math
import statistics
from collections import defaultdict

from .run import load

# Changes smaller than this are within the run-to-run noise of a desktop runner.
THRESHOLD = 0.10


def by_case(observations):
    """{(backend, route, profile): (median total_ns or None, outcomes, path costs)}"""
    grouped = defaultdict(list)
    for row in observations:
        grouped[(row["backend"], row["route_id"], row["profile"])].append(row)
    result = {}
    for key, rows in grouped.items():
        times = [r["total_ns"] for r in rows if r["outcome"] != "failed"]
        result[key] = (statistics.median(times) if times else None,
                       sorted({r["outcome"] for r in rows}),
                       sorted({r["path_cost"] for r in rows}, key=lambda c: (c is None, c)))
    return result


def compare(baseline_dir, candidate_dir, top=10):
    """A Markdown report."""
    base_run, _, base_rows = load(baseline_dir)
    cand_run, _, cand_rows = load(candidate_dir)
    base, cand = by_case(base_rows), by_case(cand_rows)
    lines = [
        f"Baseline: tooling `{base_run['tooling_commit'][:12]}`, plugin `{base_run['plugin_commit'][:12]}` "
        f"({base_run['suite']}, {base_run['runner']})",
        f"Candidate: tooling `{cand_run['tooling_commit'][:12]}`, plugin `{cand_run['plugin_commit'][:12]}` "
        f"({cand_run['suite']}, {cand_run['runner']})",
        "",
    ]
    if base_run["suite_sha256"] != cand_run["suite_sha256"]:
        lines += ["The runs used different suite definitions, so only shared cases are compared.", ""]
    lines += ["| backend | cases | geomean time | faster >10% | slower >10% | result changes |",
              "|---|---:|---:|---:|---:|---:|"]
    details = []
    for backend in sorted({k[0] for k in base} & {k[0] for k in cand}):
        keys = sorted(k for k in base.keys() & cand.keys() if k[0] == backend)
        ratios, changed = [], []
        for key in keys:
            (bt, bo, bc), (ct, co, cc) = base[key], cand[key]
            if (bo, bc) != (co, cc):
                changed.append((key, bo, bc, co, cc))
            if bt and ct:
                ratios.append((ct / bt, key, bt, ct))
        geomean = math.exp(sum(math.log(r) for r, *_ in ratios) / len(ratios)) if ratios else float("nan")
        faster = sum(1 for r, *_ in ratios if r < 1 - THRESHOLD)
        slower = sum(1 for r, *_ in ratios if r > 1 + THRESHOLD)
        lines.append(f"| {backend} | {len(keys)} | {percent(geomean)} | {faster} | {slower} | {len(changed)} |")
        worst = sorted(ratios, reverse=True)[:top]
        if worst:
            details += ["", f"Slowest changes ({backend}):", "", "| route | profile | baseline | candidate | change |",
                        "|---|---|---:|---:|---:|"]
            details += [f"| {k[1]} | {k[2]} | {ms(bt)} | {ms(ct)} | {percent(r)} |" for r, k, bt, ct in worst]
        if changed:
            details += ["", f"Result changes ({backend}):", "", "| route | profile | baseline | candidate |",
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
