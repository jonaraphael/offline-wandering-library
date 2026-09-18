#!/usr/bin/env python3
"""Run without installing OWL or any third-party dependencies."""
from pathlib import Path
import runpy

if __name__ == "__main__":
    runpy.run_path(str(Path(__file__).resolve().parents[1] / "src/owl/verify.py"), run_name="__main__")
