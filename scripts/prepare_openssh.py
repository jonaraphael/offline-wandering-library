"""Register preserved OpenSSH portable sources; this command never uses HTTP."""
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from owl.acquisition.mdoc_evidence import main

raise SystemExit(main())
