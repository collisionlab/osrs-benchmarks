"""Suites, and the scenario lists they select from a tooling checkout.

A suite selects scenarios from tooling's scenario index (every scenario of every tooling suite,
`gradle scenarioIndex`) with selectors: {"suite": NAME or "*", "tier": TIER (optional)}. Running
the same suite against a newer tooling commit picks up its new scenarios and suites.
"""
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

SUITES = Path(__file__).parent / "suites"
BACKENDS = ("legacy", "astar")


@dataclass(frozen=True)
class Suite:
    name: str
    description: str
    scenarios: tuple
    warmup: tuple
    backends: tuple
    repetitions: int
    sha256: str


def names():
    return sorted(p.stem for p in SUITES.glob("*.json"))


def check_selectors(path, field, selectors):
    for selector in selectors:
        if not isinstance(selector, dict) or not isinstance(selector.get("suite"), str) \
                or set(selector) - {"suite", "tier"}:
            raise SystemExit(f"{path}: each {field} entry is {{\"suite\": NAME or \"*\", \"tier\": TIER}}")


def load(name_or_path):
    path = Path(name_or_path)
    if not path.is_file():
        path = SUITES / f"{name_or_path}.json"
    if not path.is_file():
        raise SystemExit(f"unknown suite {name_or_path!r}; suites: {', '.join(names())}")
    raw = json.loads(path.read_text())
    expected = {"description", "scenarios", "warmup", "backends", "repetitions"}
    if set(raw) != expected:
        raise SystemExit(f"{path}: fields must be exactly {sorted(expected)}")
    check_selectors(path, "scenarios", raw["scenarios"])
    check_selectors(path, "warmup", raw["warmup"])
    if not raw["scenarios"]:
        raise SystemExit(f"{path}: scenarios must select something")
    unknown = set(raw["backends"]) - set(BACKENDS)
    if unknown or not raw["backends"]:
        raise SystemExit(f"{path}: backends must be a non-empty subset of {BACKENDS}")
    if raw["repetitions"] < 1:
        raise SystemExit(f"{path}: repetitions must be at least 1")
    canonical = json.dumps(raw, sort_keys=True, separators=(",", ":"))
    return Suite(name=path.stem, description=raw["description"], scenarios=tuple(raw["scenarios"]),
                 warmup=tuple(raw["warmup"]), backends=tuple(raw["backends"]),
                 repetitions=raw["repetitions"], sha256=hashlib.sha256(canonical.encode()).hexdigest())


def select(selectors, index):
    """[(suite, scenario name)] of the index entries any selector matches, in index order."""
    for selector in selectors:
        if selector["suite"] != "*" and selector["suite"] not in index:
            raise SystemExit(f"tooling has no scenario suite {selector['suite']!r}; it has {', '.join(index)}")
    chosen = []
    for suite, scenarios in index.items():
        for scenario in scenarios:
            if any(s["suite"] in ("*", suite) and ("tier" not in s or s["tier"] in scenario["tiers"])
                   for s in selectors):
                chosen.append((suite, scenario["name"]))
    return chosen


def manifest(suite, backend, cases, warmup):
    """The manifest tooling's benchmark task runs (its format 2).

    Repetitions are the outer loop, so a burst of background noise lands on one repetition of
    many cases rather than every repetition of one case.
    """
    return {
        "format_version": 2,
        "algorithm": backend,
        "warmup": [{"suite": s, "scenario": n} for s, n in warmup],
        "cases": [{"suite": s, "scenario": n, "repetition": repetition}
                  for repetition in range(suite.repetitions) for s, n in cases],
    }
