#!/usr/bin/env python3
"""Freeze a reproducible map proposal from cached discovery and HEAD evidence."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from owl.acquisition.map_manifest import main

if __name__ == "__main__":
    raise SystemExit(main())
