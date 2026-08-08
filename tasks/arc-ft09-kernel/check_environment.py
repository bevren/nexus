"""Safe preflight for the official ARC-AGI ft09 workspace."""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import sys


def main() -> int:
    workspace = Path(__file__).resolve().parent
    requirements = workspace / "requirements.txt"
    api_key_set = bool(os.environ.get("ARC_API_KEY", "").strip())
    toolkit_available = importlib.util.find_spec("arc_agi") is not None

    print(f"python: {sys.executable}")
    print(f"workspace: {workspace}")
    print(f"ARC_API_KEY: {'set' if api_key_set else 'not set (anonymous access will be used)'}")
    print(f"arc-agi in current interpreter: {'available' if toolkit_available else 'will be installed in workspace .venv'}")

    if not requirements.is_file():
        print("ERROR: requirements.txt is missing")
        return 1
    if "arc-agi" not in requirements.read_text(encoding="utf-8").lower():
        print("ERROR: requirements.txt does not declare arc-agi")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
