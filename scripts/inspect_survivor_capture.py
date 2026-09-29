#!/usr/bin/env python3
"""Inspect every captured book page and prepare bounded, resumable review samples.

No acquisition, OCR, catalog changes or automatic approval. Each PDF runs in a
separate timed process; the original file is streamed for whole-file integrity.
"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from owl.acquisition.capture import _digest, _json, _read, _usage, load_capture_sources
from owl.acquisition.sampling import sampling_plan
from owl.runtime import file_lock
from owl.safety import SafetyError, atomic_write, reject_symlinks, safe_path, sha256_file

VERSION = 'survivor-page-review-2'
MAX_SOURCE = 512 * 1024**2
MAX_OUTPUT = 16 * 1024**2
MAX_PAGES = 3000
MAX_RECORD = 2 * 1024**2


def write(root, target, payload, owner):
    reject_symlinks(target)
    if _read(root / 'owner.json') != owner or root not in target.parents:
        raise SafetyError('Review output owner changed')
    if len(payload) > MAX_RECORD or _usage(root) + len(payload) > owner['output_budget_bytes']:
        raise SafetyError('Review evidence exceeds the registered output bound')
    if shutil.disk_usage(root).free < owner['reserve_bytes'] + len(payload):
        raise SafetyError('Review write would consume its filesystem reserve')
    atomic_write(target, payload)


def inspect_pdf(path, source, receipt, emit):
    import pymupdf
    if (not 0 < source['size_bytes'] <= MAX_SOURCE or path.stat().st_size != source['size_bytes']
            or sha256_file(path) != receipt['sha256']):
        raise SafetyError('Captured book changed or exceeds the512MiB input bound')
    rows, samples, text_bytes = [], [], 0
    with pymupdf.open(path) as pdf:
        if pdf.is_encrypted or not 0 < len(pdf) <= MAX_PAGES:
            raise SafetyError('Encrypted PDF or page count outside1–3000')
        ids = [str(i + 1) for i in range(len(pdf))]
        plan = sampling_plan(ids, receipt['sha256'], targeted=ids[:2] + ids[-2:], screening=3)
        selected = set(plan['targeted_units'] + plan['screening_units'])
        toc, excerpts, flags = [], [], []
        for i, page in enumerate(pdf):
            if not 0 < max(page.rect.width, page.rect.height) <= 20000:
                raise SafetyError('PDF page dimensions exceed review bounds')
            text = page.get_text('text')
            encoded = text.encode(); text_bytes += len(encoded)
            if len(encoded) > 256 * 1024 or text_bytes > 32 * 1024**2:
                raise SafetyError('PDF text exceeds bounded inspection policy')
            # All pages render at thumbnail size, even when only a few pages
            # receive larger visual-review copies. This is not OCR/legibility.
            pix = page.get_pixmap(matrix=pymupdf.Matrix(96 / max(page.rect.width, page.rect.height),
                96 / max(page.rect.width, page.rect.height)), alpha=False)
            blank = max(pix.samples, default=255) - min(pix.samples, default=255) < 5
            rows.append({'page': i + 1, 'label': page.get_label(), 'text_characters': len(text.strip()),
                'text_sha256': hashlib.sha256(encoded).hexdigest(), 'image_objects': len(page.get_images()),
                'rendered': True, 'apparently_blank': blank, 'dimensions': list(page.rect)[2:]})
            if i < 20 and ('contents' in text.lower() or 'illustrations' in text.lower()):
                toc.append(i + 1)
                if len(selected) < 12: selected.add(str(i + 1))
        for number in sorted(map(int, selected)):
            page = pdf[number - 1]; text = page.get_text('text')
            scale = 1200 / max(page.rect.width, page.rect.height)
            pix = page.get_pixmap(matrix=pymupdf.Matrix(scale, scale), alpha=False)
            payload = pix.tobytes('png')
            extension = 'png'
            if len(payload) > MAX_RECORD:
                # Review images are disposable samples, not library content.
                # Keep resolution and budget; the full original remains intact.
                payload = pix.tobytes('jpeg', jpg_quality=85)
                extension = 'jpg'
            if len(payload) > MAX_RECORD or sum(r['size_bytes'] for r in samples) + len(payload) > MAX_OUTPUT - MAX_RECORD:
                raise SafetyError('Rendered review samples exceed per-book output bound')
            name = f'page-{number}.{extension}'; emit(name, payload)
            samples.append({'path': name, 'page': number, 'size_bytes': len(payload),
                'max_dimension_pixels': 1200, 'jpeg_quality': 85 if extension == 'jpg' else None,
                'sha256': hashlib.sha256(payload).hexdigest()})
            excerpts.append({'pdf_page': number, 'text': text[:1800], 'truncated': len(text) > 1800})
        text_pages = sum(r['text_characters'] >= 80 for r in rows)
        if text_pages < len(rows) * .8: flags.append('Limited searchable text; scan/OCR and topic review required')
        if any(r['apparently_blank'] for r in rows): flags.append('Apparently blank pages require TOC/page-sequence reconciliation')
        if not toc: flags.append('No table of contents located in extracted text; inspect original front matter')
        if pdf.embfile_count(): flags.append('Embedded document dependencies require review')
        for key in ('OpenAction', 'AA'):
            if pdf.xref_get_key(pdf.pdf_catalog(), key)[0] != 'null':
                flags.append('PDF document actions require review')
        return {'page_count': len(rows), 'pages': rows, 'metadata': pdf.metadata,
            'table_of_contents_candidate_pages': toc, 'text_pages': text_pages,
            'sampling': plan, 'renders': samples, 'utility_excerpts': excerpts,
            'flags': flags, 'checks': {'whole_file_hash': True, 'all_pages_rendered': True},
            'required_review': ['Match the title page, edition, contents and terminal pages to a complete work.',
                'Review topic utility and duplication against both Survivor tiers and existing books.',
                'Inspect illustrations, tables and instructions for scan legibility; retain historical warnings.',
                'Reconcile expected pages and notices; sampling does not prove completeness.']}


def worker(task):
    root = Path(task['root']); output = safe_path(root, task['source']['id'])
    binding = task['binding']; path = Path(task['source_path'])
    result = inspect_pdf(path, task['source'], task['receipt'],
        lambda name, payload: write(root, safe_path(output, name), payload, task['owner']))
    result.update(schema_version=1, status='inspected_awaiting_review', content_ready=False,
        source_id=task['source']['id'], binding=binding)
    write(root, output / 'inspection.json', _json(result), task['owner'])


def cached(path, binding):
    if not path.exists(): return None
    value = _read(path, MAX_RECORD)
    if value.get('binding') != binding or value.get('content_ready') is not False:
        raise SafetyError('Cached review belongs to changed evidence; use a new review version')
    for image in value['renders']:
        target = safe_path(path.parent, image['path'])
        if target.stat().st_size != image['size_bytes'] or sha256_file(target) != image['sha256']:
            raise SafetyError('Cached sample render changed')
    return value


def run(staging, output, budget, reserve, only_sources=()):
    import pymupdf
    staging, output = staging.absolute(), output.absolute()
    reject_symlinks(staging); reject_symlinks(output)
    if output == staging or output in staging.parents or staging in output.parents:
        raise SafetyError('Review and acquisition require separate owned roots')
    manifest, receipts = load_capture_sources(staging)
    selected = [s for s in manifest['sources'] if not only_sources or s['id'] in only_sources]
    if set(only_sources) - {s['id'] for s in selected} or not selected:
        raise SafetyError('Source review filter contains unknown identities')
    if (not 1 <= len(receipts) <= 100 or not len(selected) * MAX_OUTPUT + MAX_RECORD <= budget <= 1_000_000_000
            or reserve < 10_000_000_000):
        raise SafetyError('Review requires1–100 books, sufficient declared sample peak (at most1GB) and10GB reserve')
    owner = {'schema_version': 1, 'owner': 'owl-survivor-page-review', 'manifest_sha256': _digest(manifest),
        'output_budget_bytes': budget, 'reserve_bytes': reserve, 'source_ids': [s['id'] for s in selected]}
    marker = output / 'owner.json'
    if marker.exists():
        if _read(marker) != owner: raise SafetyError('Review ownership changed')
    else:
        if output.exists() and any(output.iterdir()): raise SafetyError('Unowned populated review directory')
        output.mkdir(parents=True, exist_ok=True); atomic_write(marker, _json(owner))
    by_id = {r['source_id']: r for r in receipts}; rows = []
    with file_lock(output / 'review.lock'):
        for source in selected:
            receipt = by_id[source['id']]
            binding = {'version': VERSION, 'code_sha256': sha256_file(Path(__file__)),
                'manifest_sha256': _digest(manifest), 'source_record_sha256': _digest(source),
                'receipt_sha256': _digest(receipt), 'source_sha256': receipt['sha256'],
                'pymupdf_version': pymupdf.VersionBind}
            path = safe_path(output, source['id'] + '/inspection.json')
            try:
                result = cached(path, binding)
                if result is None:
                    if _usage(output) + MAX_OUTPUT > budget or shutil.disk_usage(output).free < reserve + MAX_OUTPUT:
                        raise SafetyError('Insufficient room for bounded per-book review')
                    task = {'root': str(output), 'source_path': str(safe_path(staging, receipt['relative_path'])),
                        'source': source, 'receipt': receipt, 'binding': binding, 'owner': owner}
                    task_path = safe_path(output, source['id'] + '/task.json')
                    write(output, task_path, _json(task), owner)
                    subprocess.run([sys.executable, str(Path(__file__).resolve()), '--worker', str(task_path)],
                        check=True, timeout=120, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    result = cached(path, binding)
                row = {'source_id': source['id'], 'title': source.get('fullasset_metadata', {}).get('title'),
                    'status': result['status'], 'checks': result['checks'], 'page_count': result['page_count'],
                    'flags': result['flags'], 'candidate_topics': source.get('candidate_topics', []),
                    'evidence': str(path.relative_to(output)), 'evidence_sha256': sha256_file(path)}
            except (SafetyError, OSError, subprocess.SubprocessError) as error:
                failure = safe_path(output, source['id'] + '/failure.json')
                detail = _read(failure) if failure.exists() else {'error': str(error)[:500]}
                row = {'source_id': source['id'], 'status': 'failed', 'error': str(detail['error'])[:500]}
            rows.append(row)
            report = {'schema_version': 1, 'status': 'awaiting_review', 'content_ready': False,
                'manifest_sha256': _digest(manifest), 'rows': rows, 'inspected_sources': len(rows),
                'requested_sources': len(selected), 'capture_sources': len(receipts),
                'selected_source_ids': [s['id'] for s in selected],
                'failed_sources': sum(r['status'] == 'failed' for r in rows),
                'body_downloads': 0, 'accepted_useful_bytes': 0}
            write(output, output / 'report.json', _json(report), owner)
            print(json.dumps({'inspected': len(rows), 'requested': len(selected),
                'failed': report['failed_sources'], 'content_ready': False}), flush=True)
    return {k: v for k, v in report.items() if k != 'rows'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--worker', type=Path)
    parser.add_argument('--staging', type=Path)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--output-budget-bytes', type=int, default=1_000_000_000)
    parser.add_argument('--reserve-bytes', type=int, default=10_000_000_000)
    parser.add_argument('--only-source', action='append', default=[])
    args = parser.parse_args()
    if args.worker:
        task = _read(args.worker, MAX_RECORD)
        try: worker(task)
        except Exception as error:
            write(Path(task['root']), args.worker.parent / 'failure.json',
                _json({'error': str(error)[:4000], 'type': type(error).__name__}), task['owner'])
            raise SystemExit(1)
        return
    if not args.staging or not args.output: parser.error('--staging and --output are required')
    print(json.dumps(run(args.staging, args.output, args.output_budget_bytes, args.reserve_bytes, args.only_source)))


if __name__ == '__main__': main()
