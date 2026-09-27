#!/usr/bin/env python3
"""Bounded, cached inventory of OCW packages already acquired by a staging build."""
import argparse
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from owl.acquisition.ocw import inspect_capture

parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--staging-root',type=Path,required=True)
parser.add_argument('--output',type=Path,required=True)
args=parser.parse_args()
result=inspect_capture(args.staging_root,args.output)
# Detailed lesson/member records stay on disk; ordinary stdout stays bounded.
result['totals']={key:sum(c[key] for c in result['courses']) for key in
    ('files','expanded_bytes','video_lessons','unique_media','gaps')}
result['course_count']=len(result.pop('courses'))
print(json.dumps(result,sort_keys=True))
