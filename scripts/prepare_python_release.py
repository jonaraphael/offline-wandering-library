#!/usr/bin/env python3
"""Freeze an official versioned Python HTML archive and inspect complete members.

Prepare retrieves bounded publisher metadata only. Capture bodies separately
through acquire_content.py build. Members reads only that receipted original.
"""
import argparse
from copy import deepcopy
import hashlib
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from owl.acquisition.capture import normalize_manifest, load_capture_sources, _json, _digest
from owl.acquisition.metadata import Fetcher
from owl.acquisition.pins import PinProbe
from owl.archive import ZipSource
from owl.safety import SafetyError, atomic_write
from urllib.parse import urlsplit
from collections import Counter


class HTML(HTMLParser):
    def __init__(self):super().__init__();self.links=[];self.in_title=False;self.title=[]
    def handle_starttag(self,tag,attrs):
        if tag=='a' and dict(attrs).get('href'):self.links.append(dict(attrs)['href'])
        if tag=='title':self.in_title=True
    def handle_endtag(self,tag):
        if tag=='title':self.in_title=False
    def handle_data(self,data):
        if self.in_title:self.title.append(data)


def immutable(path,value):
    data=_json(value)
    if len(data)>16*1024*1024:raise SafetyError('Pending control manifest exceeds16MiB; split the proposal')
    if path.exists() and path.read_bytes()!=data:raise SafetyError('Frozen output changed; select a new proposal version')
    atomic_write(path,data)


def prepare(args):
    import yaml
    if not re.fullmatch(r'3\.[0-9]+\.[0-9]+',args.version):raise SafetyError('Expected exact stable Python release version')
    page=f'https://www.python.org/ftp/python/doc/{args.version}/';filename=f'python-{args.version}-docs-html.zip';url=page+filename
    fetcher=Fetcher(args.cache/'metadata',offline=args.offline)
    body=fetcher.fetch(page,kind='python-release-directory',max_bytes=262144)
    document=HTML();document.feed(body.decode('utf-8'));document.close()
    if filename not in document.links:raise SafetyError('Official release directory does not list this complete HTML ZIP')
    probe=PinProbe(args.cache/'pins',offline=args.offline).probe({'id':'python-release-html','url':url})
    if not probe.get('size_bytes') or probe['size_bytes']>128*1024*1024:raise SafetyError('Missing or excessive exact source size')
    probe['evidence']=[{k:v for k,v in item.items() if k!='cached'} for item in probe['evidence']]
    head=probe['evidence'][0]
    if head['status']!=200 or head['final_url']!=url:raise SafetyError('Official versioned source identity changed')
    original=next(a for a in yaml.safe_load((ROOT/'catalog/library.yaml').read_text())['assets'] if a['id']=='docs_python_html_source')
    asset=deepcopy(original);identity='docs_python_'+args.version.replace('.','_')+'_release_html_source'
    asset.update(id=identity,title=f'Python{args.version} official release HTML documentation source',source_url=url,source_page=page,
        destination=f'REFERENCE/COMPUTING/SOURCES/{filename}',version=args.version+' official release archive',size_bytes=probe['size_bytes'],
        sha256=probe['sha256'],snapshot_date=head['checked_at'][:10])
    evidence=[{k:v for k,v in item.items() if k!='cached'} for item in fetcher.evidence]
    evidence.append({'kind':'source-head','url':url,'sha256':_digest(head),'headers':head['headers'],'body_read':False})
    manifest=normalize_manifest({'schema_version':1,'kind':'acquisition','id':'python-'+args.version.replace('.','-')+'-release-html-trial',
        'profile':'full-1tb','content_ready':False,'sources':[{'id':identity,'source_url':url,'version':asset['version'],'size_bytes':asset['size_bytes'],
            'sha256':asset['sha256'],'resource_ids':['linux-programming-docs'],'publisher_checksums':{},'metadata_evidence':evidence,'fullasset_metadata':asset}],
        'budget':{'download_bytes':asset['size_bytes'],'expanded_bytes':128*1024*1024,'preview_bytes':0,'scratch_bytes':1048576,'cache_bytes':0},
        'review_requirements':['Distinct official release edition; replaces no current PDF or accepted HTML package until reviewed.',
            'Inspect every archive member and notice, preserve complete directories, reject duplicates and path collisions.']})
    immutable(args.output,manifest);immutable(args.output.with_suffix('.metadata.json'),{'publisher_directory':evidence[0],'source_probe':probe})
    return {'manifest':str(args.output),'sources':1,'source_bytes':asset['size_bytes'],'body_downloads':0,'content_ready':False}


def members(args):
    manifest,receipts=load_capture_sources(args.staging)
    if len(manifest['sources'])!=1:raise SafetyError('Expected exactly one frozen Python release source')
    source=manifest['sources'][0];receipt=receipts[0];asset=deepcopy(source['fullasset_metadata']);asset['sha256']=receipt['sha256']
    version=source['version'].split()[0];prefix='python-'+version+'-docs-html/'
    rows=[];payload=0
    with ZipSource(args.staging/receipt['relative_path'],asset) as archive:
        for name,info in sorted(archive.entries.items()):
            if not name.startswith(prefix):raise SafetyError('Publisher ZIP contains an unexpected release root')
            digest=hashlib.sha256();count=0;chunks=[];is_html=name.endswith(('.html','.htm'))
            with archive.archive.open(info) as stream:
                while block:=stream.read(min(1024*1024,info.file_size-count+1)):
                    count+=len(block)
                    if count>info.file_size:raise SafetyError('Member exceeded declared size')
                    digest.update(block)
                    if is_html and info.file_size<=8*1024*1024:chunks.append(block)
            if count!=info.file_size:raise SafetyError('Truncated member')
            title=None
            if chunks:
                parsed=HTML();parsed.feed(b''.join(chunks).decode('utf-8-sig'));parsed.close();title=' '.join(parsed.title).strip()
            document=is_html and bool(title) and Path(name).name not in {'search.html','genindex.html','py-modindex.html','index.html'} and not Path(name).name.startswith('genindex-')
            suffix=Path(name).suffix.lower();fmt='html' if is_html else {'png':'png','jpg':'jpg','jpeg':'jpg','svg':'svg','css':'css','js':'js','txt':'txt'}.get(suffix[1:],'data')
            member=deepcopy(asset);member.pop('supporting_file',None)
            member.update(id='docs_python_'+version.replace('.','_')+'_release_'+hashlib.sha256(name.encode()).hexdigest()[:20],
                title=('Python'+version+': '+title) if document else 'Python'+version+' supporting member: '+Path(name).name,
                format=fmt,destination='REFERENCE/COMPUTING/'+name,size_bytes=count,sha256=digest.hexdigest(),reader_required=False,
                resource_type='reference',supporting_file=not document,
                archive_member={'source_asset_id':asset['id'],'path':name,'document':document})
            rows.append(member);payload+=count
        archive.check_source()
    if payload>manifest['budget']['expanded_bytes']:raise SafetyError('Complete release expansion exceeds frozen budget')
    required={prefix+name for name in ('index.html','license.html','copyright.html')}
    if not required<={r['archive_member']['path'] for r in rows}:raise SafetyError('Complete release index/license/copyright pages absent')
    result={'schema_version':1,'kind':'pending-python-release-members','content_ready':False,'status':'pending_review',
        'source_id':asset['id'],'source_sha256':asset['sha256'],'source_bytes':asset['size_bytes'],'expanded_bytes':payload,'member_count':len(rows),
        'reading_documents':sum(r['archive_member']['document'] for r in rows),'assets':[asset,*rows],
        'capture_binding':{'manifest_sha256':_digest(manifest),'source_receipt_sha256':_digest(receipt)},
        'blockers':['Full package offline browser/dependency/notice review remains required; this proposal does not replace the accepted mutable-build edition.',
            'Keep all existing small-preset PDF records and source/notice dependencies unchanged.']}
    immutable(args.output,result)
    return {k:result[k] for k in ('source_id','source_sha256','source_bytes','expanded_bytes','member_count','reading_documents','content_ready')}


def localize(args):
    from owl.acquisition.zip_localized import rewrite_member, validate_recipe
    from owl.acquisition.python_manual import RUNTIME_MEMBERS, auxiliary
    proposal=json.loads(args.fragment.read_text());source_id=proposal['source_id']
    manifest,receipts=load_capture_sources(args.staging);receipt=next(r for r in receipts if r['source_id']==source_id)
    assets=deepcopy(proposal['assets']);source=next(a for a in assets if a['id']==source_id)
    if source['sha256']!=receipt['sha256']:raise SafetyError('Proposal source pin differs from capture')
    originals=[a for a in assets if a.get('archive_member')];paths={a['archive_member']['path'] for a in originals}
    identity='python-'+source['version'].split()[0].replace('.','-')+'-release-local-layout-v4'
    records=[];outputs=[];repair_count=0
    class Links(HTMLParser):
        def __init__(self):super().__init__(convert_charrefs=True);self.links=[]
        def handle_starttag(self,tag,attrs):
            self.links.extend((name,value) for name,value in attrs if name in {'href','src'} and value and value.startswith('/') and not value.startswith('//'))
        handle_startendtag=handle_starttag
    with ZipSource(args.staging/receipt['relative_path'],source) as archive:
        preliminary=[{'path':a['archive_member']['path'],'size_bytes':a['size_bytes'],'sha256':a['sha256'],
            'runtime_patch':next((key for key,suffix in RUNTIME_MEMBERS.items() if a['archive_member']['path'].endswith(suffix)),None)} for a in originals]
        runtime_inputs=auxiliary(archive,preliminary)
        for asset in originals:
            name=asset.pop('archive_member')['path'];repairs=[]
            if asset['format']=='html':
                if archive.entries[name].file_size>16*1024*1024:raise SafetyError('HTML source exceeds bounded localization size')
                data=archive.archive.read(name)
                if len(data)>16*1024*1024:raise SafetyError('HTML source exceeds bounded localization size')
                parsed=Links();parsed.feed(data.decode('utf-8'));parsed.close()
                root=name.split('/')[0]+'/'
                for (attribute,value),count in sorted(Counter(parsed.links).items()):
                    url=urlsplit(value);relative=url.path.lstrip('/')
                    if re.match(r'^3\.[0-9]+/',relative):relative=relative.split('/',1)[1]
                    target=root+relative
                    if target not in paths:raise SafetyError('Root-relative publisher link has no exact package target: '+value)
                    repairs.append({'attribute':attribute,'from':value,'target_member':target,'expected_count':count})
                    repair_count+=count
            output_id=asset['id']+'_local'
            record={'asset_id':output_id,'path':name,'size_bytes':asset['size_bytes'],'sha256':asset['sha256'],'rewrites':repairs}
            if name.endswith('/_static/pydoctheme.css'):
                record['stylesheet_patch']='python-responsive-v2'
                data=archive.archive.read(name)
            patch=next((key for key,suffix in RUNTIME_MEMBERS.items() if name.endswith(suffix)),None)
            if patch:
                record['runtime_patch']=patch
                data=archive.archive.read(name)
            if repairs or record.get('stylesheet_patch') or patch:
                localized=rewrite_member(data,record,runtime_inputs);asset.update(size_bytes=len(localized),sha256=hashlib.sha256(localized).hexdigest())
            asset.update(id=output_id,generation={'recipe_id':identity},version=source['version']+'; OWL counted local links and offline runtime and layout v4')
            outputs.append(asset);records.append(record)
        archive.check_source()
    recipe={'id':identity,'resource_id':'linux-programming-docs','adapter':'zip_localized','version':'4',
        'source_asset_ids':[source_id],'output_asset_ids':[a['id'] for a in outputs],'workspace_bytes':100_000_000,
        'selection':{'source_asset_id':source_id,'members':records},'review':{'status':'pending','evidence':[]},
        'blockers':['Pending full generated-file pins, offline browser/dependency review and source-notice confirmation.'], 'metadata_sources':[]}
    validate_recipe(recipe,{a['id']:a for a in [source,*outputs]})
    result={'schema_version':1,'kind':'pending-localized-python-release','content_ready':False,'source_id':source_id,'assets':[source,*outputs],
        'recipes':[recipe],'repaired_attribute_spans':repair_count,'unmodified_member_count':sum(not r['rewrites'] and not r.get('stylesheet_patch') and not r.get('runtime_patch') for r in records),
        'capture_binding':proposal['capture_binding'],'notes':['The original publisher ZIP remains unchanged. Exact counted href/src repairs, fixed responsive theme append and source-bound file-mode search/feedback runtime changes retain every publisher member and all reading text.',
            'Publisher PAGEURL placeholder remains an explicitly recorded non-reading feedback-link gap; physical-device certification remains pending.']}
    immutable(args.output,result);immutable(args.output.with_suffix('.recipe.json'),recipe)
    return {'members':len(records),'repaired_attribute_spans':repair_count,'output_bytes':sum(a['size_bytes'] for a in outputs),'content_ready':False,'fragment':str(args.output)}


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('command',choices=['prepare','members','localize'])
    parser.add_argument('--version');parser.add_argument('--staging',type=Path);parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--fragment',type=Path)
    parser.add_argument('--cache',type=Path,default=ROOT/'.owl/acquisition/python-release-metadata');parser.add_argument('--offline',action='store_true')
    args=parser.parse_args()
    if args.command=='prepare' and not args.version or args.command in {'members','localize'} and not args.staging or args.command=='localize' and not args.fragment:parser.error('Need --version for prepare, --staging for members/localize, --fragment for localize')
    print(json.dumps({'prepare':prepare,'members':members,'localize':localize}[args.command](args)))


if __name__=='__main__':main()
