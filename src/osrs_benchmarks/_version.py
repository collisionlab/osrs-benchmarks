"""The harness revision recorded with every run."""
import subprocess
from pathlib import Path

# The Nix package replaces this line with the flake's revision.
VERSION = "dev"

if VERSION == "dev":
    # Running from a source checkout: the checkout's commit, marked when it has changes.
    try:
        root = Path(__file__).resolve().parents[2]
        commit = subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"], check=True, text=True,
                                capture_output=True).stdout.strip()
        dirty = subprocess.run(["git", "-C", str(root), "status", "--porcelain"], check=True, text=True,
                               capture_output=True).stdout.strip()
        VERSION = commit + ("-dirty" if dirty else "")
    except (OSError, subprocess.CalledProcessError):
        pass
