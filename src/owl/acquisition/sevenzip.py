"""Allowlisted, bounded 7z member streams; no directory extraction or shell.

Production extraction requires source and member SHA-256 pins. The separate
observe_members API produces review candidates from an already pinned source.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import threading

from ..download import verified
from ..safety import SafetyError, atomic_write, reject_symlinks, safe_path, validate_relative

LIST_BYTES = 8 * 1024 * 1024
ERROR_BYTES = 64 * 1024


def preflight():
    for name in ('7zz', '7z', '7za'):
        if executable := shutil.which(name):
            return executable
    raise SafetyError('7z acquisition requires an already installed 7zz, 7z or 7za executable')


def _run(arguments, *, limit, timeout, sink=None):
    process = subprocess.Popen(arguments, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE, close_fds=True)
    chunks, errors, failures = [], bytearray(), []
    count = 0
    def stop(error):
        failures.append(error)
        try: process.kill()
        except ProcessLookupError: pass
    def read_output():
        nonlocal count
        try:
            while data := process.stdout.read(65536):
                count += len(data)
                if count > limit:
                    raise SafetyError('7z output exceeded its declared byte bound')
                if sink is None: chunks.append(data)
                else: sink(data)
        except BaseException as error:
            stop(error)
        finally: process.stdout.close()
    def read_error():
        try:
            while data := process.stderr.read(8192):
                if len(errors) + len(data) > ERROR_BYTES:
                    raise SafetyError('7z diagnostics exceeded their byte bound')
                errors.extend(data)
        except BaseException as error:
            stop(error)
        finally: process.stderr.close()
    threads = [threading.Thread(target=read_output),threading.Thread(target=read_error)]
    for thread in threads: thread.start()
    try:
        process.wait(timeout=timeout)
    except subprocess.TimeoutExpired as error:
        stop(SafetyError('7z extraction exceeded its time limit'))
        process.wait()
    except BaseException:
        stop(SafetyError('7z extraction interrupted'))
        process.wait()
        raise
    finally:
        for thread in threads: thread.join()
    if failures: raise failures[0]
    if process.returncode:
        raise SafetyError('7z failed: ' + errors.decode('utf-8',errors='replace')[-512:])
    return b''.join(chunks) if sink is None else count


def _path(value):
    validate_relative(value)
    if (not value or '\\' in value or ':' in value or any(ord(c)<32 for c in value) or
            value.endswith('/') or len(value)>1024):
        raise SafetyError('Unsafe 7z member path')
    return value


def _limits(max_bytes,max_files,timeout):
    if type(max_bytes) is not int or max_bytes <= 0 or type(max_files) is not int or not 1 <= max_files <= 100000:
        raise SafetyError('7z extraction needs positive byte and bounded file allowances')
    if not isinstance(timeout,(int,float)) or isinstance(timeout,bool) or not 0 < timeout <= 3600:
        raise SafetyError('7z timeout must be positive and at most 3600 seconds')


def inspect_archive(source, source_asset, *, max_bytes, max_files, timeout=60):
    _limits(max_bytes,max_files,timeout)
    source = Path(source)
    reject_symlinks(source)
    if not verified(source,source_asset['size_bytes'],source_asset['sha256']):
        raise SafetyError('7z source archive hash/size mismatch')
    with source.open('rb') as handle:
        if handle.read(6) != b'7z\xbc\xaf\x27\x1c':
            raise SafetyError('7z extractor accepts only 7z archives; ZIP uses its separate verified path')
    data = _run([preflight(),'l','-slt','-ba','-bd','-sccUTF-8','-p-','--',str(source)],
                limit=LIST_BYTES,timeout=timeout).decode('utf-8',errors='strict')
    result, seen, expanded = [], set(), 0
    for block in re.split(r'\r?\n\s*\r?\n',data.strip()):
        values = {}
        for line in block.splitlines():
            if ' = ' in line:
                key,value=line.split(' = ',1)
                if key in values: raise SafetyError('Duplicate 7z metadata field')
                values[key]=value
        if 'Path' not in values: continue
        if values.get('Type') == '7z' and 'Size' not in values: continue
        name = _path(values['Path'].rstrip('/'))
        folded = name.casefold()
        if folded in seen: raise SafetyError('Duplicate or case-colliding 7z member paths')
        seen.add(folded)
        if len(seen)>max_files: raise SafetyError('7z member count exceeds its bound')
        if (values.get('Encrypted','-') != '-' or any('link' in key.lower() for key in values) or
                re.search(r'\bl[rwx-]{9}\b',values.get('Attributes',''))):
            raise SafetyError('Encrypted or linked 7z members are unsupported')
        if values.get('Folder') == '+' or values.get('Attributes','').startswith('D'): continue
        try: size=int(values['Size'])
        except (KeyError,ValueError) as error: raise SafetyError('7z member lacks an exact size') from error
        if size < 0: raise SafetyError('Negative 7z member size')
        expanded += size
        if expanded>max_bytes: raise SafetyError('7z expanded bytes exceed their bound')
        result.append({'path':name,'size_bytes':size})
    if not result: raise SafetyError('7z archive has no supported regular members')
    return result


def _extract(source,source_asset,members,output_dir,*,max_bytes,max_files,timeout,observe,progress,before_write):
    _limits(max_bytes,max_files,timeout)
    listing={row['path']:row for row in inspect_archive(source,source_asset,max_bytes=max_bytes,max_files=max_files,timeout=min(timeout,60))}
    if not isinstance(members,list) or not members or len(members)>max_files:
        raise SafetyError('7z member selection must be a nonempty bounded allowlist')
    seen=set()
    for row in members:
        if not isinstance(row,dict) or set(row)-{'path','size_bytes','sha256'} or not {'path','size_bytes'}<=row.keys():
            raise SafetyError('7z selection needs path, size_bytes and reviewed SHA-256')
        name=_path(row['path'])
        if name.casefold() in seen: raise SafetyError('Duplicate selected 7z member')
        seen.add(name.casefold())
        if name not in listing or type(row['size_bytes']) is not int or row['size_bytes'] != listing[name]['size_bytes']:
            raise SafetyError('7z allowlist differs from the pinned archive inventory')
        checksum=row.get('sha256')
        if (checksum is not None and (not isinstance(checksum,str) or not re.fullmatch('[0-9a-f]{64}',checksum))) or (not observe and checksum is None):
            raise SafetyError('Production 7z extraction requires whole-member SHA-256 pins')
    output_dir=Path(output_dir)
    reject_symlinks(output_dir)
    owner={'owner':'owl-sevenzip','source_sha256':source_asset['sha256'],'members':members,'observe_only':observe}
    if len(json.dumps(owner).encode()) + 80 * len(members) > 65536:
        raise SafetyError('7z allowlist metadata exceeds its 64 KiB bound; split the reviewed selection')
    marker=safe_path(output_dir,'.owl-sevenzip.json')
    if output_dir.exists():
        if not marker.is_file() or marker.stat().st_size>LIST_BYTES or json.loads(marker.read_text())!=owner:
            raise SafetyError('7z extraction directory belongs to another selection')
    else:
        output_dir.mkdir(parents=True)
        atomic_write(marker,(json.dumps(owner,sort_keys=True)+'\n').encode())
    saved_path=safe_path(output_dir,'members.json')
    saved={}
    if saved_path.is_file():
        if saved_path.stat().st_size>65536: raise SafetyError('7z member receipt exceeds its metadata bound')
        saved={item['path']:item for item in json.loads(saved_path.read_text())}
    paths,receipts={},[]
    for row in members:
        name=row['path']; destination=safe_path(output_dir,'files/'+name)
        checksum=row.get('sha256') or (saved.get(name,{}).get('sha256') if observe else None)
        if checksum and verified(destination,row['size_bytes'],checksum):
            digest=checksum
        else:
            if destination.exists():
                raise SafetyError('Existing extracted member is unpinned or changed; use a new review directory')
            part=safe_path(output_dir,'.parts/'+hashlib.sha256(name.encode()).hexdigest()+'.part')
            part.parent.mkdir(exist_ok=True)
            digest=hashlib.sha256()
            progress('EXTRACT 7z '+name)
            with part.open('wb') as handle:
                def sink(data):
                    if before_write is not None: before_write(len(data))
                    handle.write(data)
                    digest.update(data)
                _run([preflight(),'x','-so','-bd','-y','-p-','-spd','-ssc','-mmt=1','--',str(source),name],
                     limit=row['size_bytes'],timeout=timeout,sink=sink)
                handle.flush()
                import os
                os.fsync(handle.fileno())
            digest=digest.hexdigest()
            if part.stat().st_size != row['size_bytes'] or (row.get('sha256') and digest != row['sha256']):
                raise SafetyError('7z member hash/size differs from its reviewed pin')
            destination.parent.mkdir(parents=True,exist_ok=True)
            part.replace(destination)
        paths[name]=destination
        receipts.append({**row,'sha256':digest})
        # Completed siblings survive a later interrupted member, including the
        # explicitly unapproved observation workflow.
        atomic_write(saved_path,(json.dumps(receipts,sort_keys=True)+'\n').encode())
    return {'members':receipts,'paths':paths}


def extract(source,source_asset,members,output_dir,*,max_bytes,max_files,timeout=300,progress=print,before_write=None):
    return _extract(source,source_asset,members,output_dir,max_bytes=max_bytes,max_files=max_files,
                    timeout=timeout,observe=False,progress=progress,before_write=before_write)['paths']


def observe_members(source,source_asset,members,output_dir,*,max_bytes,max_files,timeout=300,progress=print,before_write=None):
    """Acquire local review evidence only; observations never approve a recipe."""
    return _extract(source,source_asset,members,output_dir,max_bytes=max_bytes,max_files=max_files,
                    timeout=timeout,observe=True,progress=progress,before_write=before_write)
