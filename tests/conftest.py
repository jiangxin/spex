"""Shared test configuration — ensure scripts/ is importable."""

import sys
from pathlib import Path

# Add scripts/ to sys.path so tests can import modules directly.
_scripts_dir = str(Path(__file__).resolve().parent.parent / "scripts")
if _scripts_dir not in sys.path:
    sys.path.insert(0, _scripts_dir)
