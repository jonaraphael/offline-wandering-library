#!/usr/bin/env python3
"""Freeze exact publisher course-media identities from bounded metadata only."""
import argparse,json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from owl.acquisition.ocw_media import prepare
p=argparse.ArgumentParser(description=__doc__)
p.add_argument('--inventories',type=Path,required=True)
p.add_argument('--cache-dir',type=Path,default=Path('.owl/acquisition/ocw-media-metadata'))
p.add_argument('--output',type=Path,required=True)
p.add_argument('--offline',action='store_true')
p.add_argument('--course-source',action='append',default=[])
p.add_argument('--id',default='ocw-foundational-media-v1')
a=p.parse_args()
print(json.dumps(prepare(a.inventories,a.cache_dir,a.output,offline=a.offline,
    course_sources=a.course_source,identity=a.id),sort_keys=True))
