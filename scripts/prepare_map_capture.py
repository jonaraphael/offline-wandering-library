#!/usr/bin/env python3
"""Prepare exact-sized map candidates for an explicit source-review build."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from owl.acquisition.map_capture import main

if __name__ == "__main__":
    raise SystemExit(main())
