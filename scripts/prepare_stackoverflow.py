#!/usr/bin/env python3
"""Inspect and expand captured Stack Overflow sources once; never download or approve."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from owl.acquisition import stackoverflow_trial as trial
from owl.safety import atomic_write


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    commands=parser.add_subparsers(dest='command',required=True)
    inspect=commands.add_parser('inspect')
    inspect.add_argument('--staging-root',type=Path,required=True)
    inspect.add_argument('--output',type=Path,required=True)
    inspect.add_argument('--tool-directory',type=Path,help='Directory containing a reviewed installed 7z executable')
    inspect.add_argument('--max-expanded-bytes',type=int,default=650_000_000_000)
    inspect.add_argument('--wait-for-job',type=Path,help='Wait for an existing source capture job before inspection')
    inspect.add_argument('--wait-seconds',type=int,default=7200)
    expand=commands.add_parser('expand')
    expand.add_argument('--staging-root',type=Path,required=True)
    expand.add_argument('--inspection',type=Path,required=True)
    for field in ('expanded','scratch','preview','budget','reserve'):
        expand.add_argument('--'+field+'-bytes',type=int,required=True)
    select=commands.add_parser('select')
    select.add_argument('--staging-root',type=Path,required=True)
    select.add_argument('--shared-expansion',type=Path,required=True)
    select.add_argument('--cache-dir',type=Path,required=True)
    select.add_argument('--output',type=Path,required=True)
    select.add_argument('--limit',type=int,default=100000)
    args=parser.parse_args(argv)
    if args.command=='inspect':
        if args.tool_directory:
            import os
            from owl.safety import reject_symlinks
            reject_symlinks(args.tool_directory)
            if not args.tool_directory.is_dir():raise ValueError('7z tool directory is absent')
            os.environ['PATH']=str(args.tool_directory.absolute())+os.pathsep+os.environ.get('PATH','')
        if args.wait_for_job:
            import time
            from owl.jobs import status_job
            if not 1<=args.wait_seconds<=7200:raise ValueError('Job wait must be between 1 and 7200 seconds')
            deadline=time.monotonic()+args.wait_seconds;last=None
            while True:
                status=status_job(args.wait_for_job)
                if status['state'] in {'complete','awaiting_review'}:break
                if status['state'] in {'failed','cancelled','interrupted'}:
                    raise RuntimeError('Source capture job stopped: '+status['state'])
                marker=(status['state'],status.get('completed_assets'))
                if marker!=last:
                    print('WAIT source capture: '+str(marker),file=sys.stderr,flush=True);last=marker
                remaining=deadline-time.monotonic()
                if remaining<=0:raise TimeoutError('Bounded source capture wait expired')
                time.sleep(min(30,remaining))
        result=trial.inspect(args.staging_root,max_expanded_bytes=args.max_expanded_bytes,
                             progress=lambda value:print(value,file=sys.stderr))
        atomic_write(args.output,(json.dumps(result,sort_keys=True,indent=2)+'\n').encode())
        result={key:result[key] for key in ('content_ready','download_bytes','xml_bytes','expanded_bytes','metadata_allowance_bytes')}
    elif args.command=='expand':
        result=trial.expand(args.staging_root,args.inspection,expanded_bytes=args.expanded_bytes,scratch_bytes=args.scratch_bytes,
            preview_bytes=args.preview_bytes,budget_bytes=args.budget_bytes,reserve_bytes=args.reserve_bytes,
            progress=lambda value:print(value,file=sys.stderr))
    else:
        from collections import Counter
        result=trial.select(args.staging_root,args.shared_expansion,cache_dir=args.cache_dir,limit=args.limit)
        payload=(json.dumps(result,sort_keys=True,ensure_ascii=False)+'\n').encode()
        if len(payload)>64*1024*1024:raise ValueError('Candidate evidence exceeded 64 MiB')
        atomic_write(args.output,payload)
        counts=dict(Counter(row['bucket'] for row in result['candidates']))
        ambiguous=len(result['review_queue'])
        result={key:result[key] for key in ('content_ready','cache_hit','scanned_questions','excluded_questions','selection_limit')} | {
            'candidate_buckets':counts,'ambiguous_versions':ambiguous}
    print(json.dumps(result,sort_keys=True,indent=2))
    return 0


if __name__=='__main__':raise SystemExit(main())
