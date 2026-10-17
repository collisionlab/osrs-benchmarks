"""Suites, and the case lists they expand to for a tooling checkout."""
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

SUITES = Path(__file__).parent / "suites"
BACKENDS = ("legacy", "astar")
# The benchmark project name tooling's BenchmarkMain expects for each backend.
PROJECTS = {"legacy": "shortest-path", "astar": "shortest-path-astar"}
ROUTES = Path("corpus/corpus/routes-v1.json")


@dataclass(frozen=True)
class Suite:
    name: str
    description: str
    tier: str
    profiles: tuple
    backends: tuple
    repetitions: int
    warmup: bool
    account_clock_minutes: int
    sha256: str


def names():
    return sorted(p.stem for p in SUITES.glob("*.json"))


def load(name_or_path):
    path = Path(name_or_path)
    if not path.is_file():
        path = SUITES / f"{name_or_path}.json"
    if not path.is_file():
        raise SystemExit(f"unknown suite {name_or_path!r}; suites: {', '.join(names())}")
    raw = json.loads(path.read_text())
    expected = {"description", "tier", "profiles", "backends", "repetitions", "warmup",
                "account_clock_minutes"}
    if set(raw) != expected:
        raise SystemExit(f"{path}: fields must be exactly {sorted(expected)}")
    unknown = set(raw["backends"]) - set(BACKENDS)
    if unknown or not raw["backends"]:
        raise SystemExit(f"{path}: backends must be a non-empty subset of {BACKENDS}")
    if raw["repetitions"] < 1:
        raise SystemExit(f"{path}: repetitions must be at least 1")
    canonical = json.dumps(raw, sort_keys=True, separators=(",", ":"))
    return Suite(name=path.stem, description=raw["description"], tier=raw["tier"],
                 profiles=tuple(raw["profiles"]), backends=tuple(raw["backends"]),
                 repetitions=raw["repetitions"], warmup=raw["warmup"],
                 account_clock_minutes=raw["account_clock_minutes"],
                 sha256=hashlib.sha256(canonical.encode()).hexdigest())


def cases(suite, tooling_dir):
    """(route_id, profile, expected_reachable) for every logical case, in corpus order."""
    routes = json.loads((Path(tooling_dir) / ROUTES).read_text())
    result = []
    for route in routes:
        if suite.tier not in route["tiers"]:
            continue
        negative = set(route.get("negativeProfiles", []))
        for profile in suite.profiles:
            result.append((route["id"], profile, profile not in negative))
    if not result:
        raise SystemExit(f"suite {suite.name}: no routes in tier {suite.tier!r}")
    return result


def manifest(suite, backend, logical_cases):
    """The case list tooling's benchmarkCanonical task runs (its manifest format 1).

    Repetitions are the outer loop, so a burst of background noise lands on one repetition of
    many cases rather than every repetition of one case.
    """
    return {
        "format_version": 1,
        "project": PROJECTS[backend],
        "policy": {
            "repetitions": suite.repetitions,
            "warmup": suite.warmup,
            "synthetic_benchmark_time": suite.account_clock_minutes,
            "adapter_args": {"algorithm": backend},
        },
        "cases": [
            {"route_id": route, "profile": profile, "repetition": repetition,
             "expected_reachable": reachable}
            for repetition in range(suite.repetitions)
            for route, profile, reachable in logical_cases
        ],
    }
