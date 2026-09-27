#!/usr/bin/env python3
"""Inspect captured map PDFs in bounded workers, preserving pending review."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from owl.acquisition.map_review import main

if __name__ == "__main__":
    raise SystemExit(main())
