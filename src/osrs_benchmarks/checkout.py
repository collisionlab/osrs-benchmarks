"""The tooling and plugin revisions a run measures.

Tooling (osrs-pathfinding/shortest-path-tooling) holds the benchmark entry point, the routes and
the accounts; it pins the plugin (Skretzo/shortest-path) as its shortest-path submodule. A run
measures tooling at some revision with either its pinned plugin or another plugin revision.
"""
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

TOOLING_REPO = "https://github.com/osrs-pathfinding/shortest-path-tooling.git"
PLUGIN_REPO = "https://github.com/Skretzo/shortest-path.git"
SUBMODULE = "shortest-path"


@dataclass(frozen=True)
class Revision:
    commit: str
    commit_time: datetime
    dirty: bool


@dataclass(frozen=True)
class Checkout:
    tooling_dir: Path
    plugin_dir: Path
    tooling: Revision
    plugin: Revision


def git(directory, *args):
    return subprocess.run(["git", "-C", str(directory), *args], check=True, text=True,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE).stdout.strip()


def revision(directory):
    commit = git(directory, "rev-parse", "HEAD")
    seconds = int(git(directory, "show", "-s", "--format=%ct", "HEAD"))
    dirty = bool(git(directory, "status", "--porcelain", "--untracked-files=no"))
    return Revision(commit, datetime.fromtimestamp(seconds, timezone.utc), dirty)


def fetch(directory, repo, ref):
    """Check out ref of repo in directory (cloned on first use), detached and clean."""
    directory = Path(directory)
    if not (directory / ".git").exists():
        directory.mkdir(parents=True, exist_ok=True)
        git(directory, "init", "-q")
    git(directory, "fetch", "-q", "--depth", "1", repo, ref)
    git(directory, "checkout", "-q", "--force", "--detach", "FETCH_HEAD")
    git(directory, "clean", "-q", "-ffdx", "-e", "/build/", "-e", "/.gradle/")
    return directory


def remote_head(repo, ref):
    """The commit ref names in repo, without fetching it."""
    out = subprocess.run(["git", "ls-remote", repo, ref], check=True, text=True,
                         stdout=subprocess.PIPE).stdout.split()
    if not out:
        raise SystemExit(f"{repo} has no ref {ref}")
    return out[0]


def pinned_plugin(tooling_dir):
    """The plugin commit tooling's submodule pins."""
    entry = git(tooling_dir, "ls-tree", "HEAD", SUBMODULE).split()
    if len(entry) < 3 or entry[1] != "commit":
        raise SystemExit(f"{tooling_dir} has no {SUBMODULE} submodule")
    return entry[2]


def prepare(work, tooling_ref=None, tooling_dir=None, plugin_ref=None, plugin_repo=PLUGIN_REPO,
            plugin_dir=None, tooling_repo=TOOLING_REPO):
    """Resolve the revisions to measure, fetching into work/ unless directories are given.

    A given directory is used as it is, uncommitted changes included (recorded as dirty).
    """
    work = Path(work)
    if tooling_dir is None:
        tooling_dir = fetch(work / "tooling", tooling_repo, tooling_ref or "master")
    tooling_dir = Path(tooling_dir).resolve()
    if plugin_dir is None:
        plugin_dir = fetch(work / "plugin", plugin_repo, plugin_ref or pinned_plugin(tooling_dir))
    plugin_dir = Path(plugin_dir).resolve()
    return Checkout(tooling_dir, plugin_dir, revision(tooling_dir), revision(plugin_dir))
