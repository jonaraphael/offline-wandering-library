"""Register the previously reviewed food snapshot from local evidence, without HTTP.

Usage: python scripts/prepare_existing_evidence.py HEALTH_EVIDENCE_DIR OUTPUT_DIR
The output is a stageable metadata fragment, not a new download or an SSD build.
"""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from owl.acquisition.evidence import main

raise SystemExit(main())
