"""Freeze the existing OpenSSH portable source evidence without fetching bodies."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import tarfile

from ..catalog import load_catalog, read_yaml
from ..safety import atomic_write, reject_symlinks, sha256_file
from .mdoc import PROBE, _mandoc, render
from .documents import _Tree, _walk, _text


def _body(path: Path) -> dict:
    nodes = [node for node in _walk(_Tree(path.read_text(encoding='utf-8')).root)
             if node.attrs.get('class') == 'manual-text']
    if len(nodes) != 1:
        raise ValueError('Expected one complete rendered manual body')
    text = re.sub(r'\s+', ' ', _text(nodes[0])).strip()
    return dict(normalized_body_sha256=hashlib.sha256(text.encode()).hexdigest(),
                body_characters=len(text),tables=sum(n.tag=='table' for n in _walk(nodes[0])))


def prepare(evidence_dir: Path, output: Path, catalog: Path, resources: Path) -> dict:
    reject_symlinks(evidence_dir)
    reject_symlinks(output)
    if output.exists():
        raise ValueError('Choose a new output directory for reviewed evidence')
    existing = load_catalog(catalog)
    source = next(a for a in existing if a['id'] == 'docs_openssh_105p1_source')
    archive = evidence_dir / 'openssh-10.5p1.tar.gz'
    if archive.stat().st_size != source['size_bytes'] or sha256_file(archive) != source['sha256']:
        raise ValueError('Existing OpenSSH source differs from the admitted original pin')
    edition = 'OpenSSH portable 10.5p1'
    recipe_id = 'openssh-portable-10-5p1-v1'
    evidence = ['docs/acquisition-openssh.md', 'catalog/acquisition/openssh-portable-evidence.json']
    prefix = 'REFERENCE/COMPUTING/OPENSSH_PORTABLE_10_5P1/'
    assets, manuals = [], []
    def asset(identity, name, title, fmt, supporting=False):
        row = {**source, 'id':identity, 'title':title, 'format':fmt, 'destination':prefix + name,
               'version':edition + '; OWL mdoc adapter v1', 'size_bytes':1, 'sha256':'0' * 64,
               'category':'computing', 'resource_type':'reference', 'supporting_file':supporting,
               'description':'Complete manual or notice rendered/extracted from the pinned portable release. '
                             'The original source companion preserves per-file notices. This is a distinct '
                             'edition from the former OpenBSD 7.9 selection.',
               'tags':['programming','computing','reference'],
               'generation':{'recipe_id':recipe_id}}
        assets.append(row)
        return identity
    with tarfile.open(archive) as tar:
        names = sorted(m.name for m in tar.getmembers() if re.fullmatch(r'openssh-10\.5p1/(?:contrib/)?[^/]+\.[158]',m.name))
        if len(names) != 16:
            raise ValueError('Expected all 16 ordinary manuals in this reviewed portable release')
        for name in names:
            basename = Path(name).name
            identity = 'docs_openssh_105p1_' + re.sub('[^a-z0-9]+','_',basename)
            manuals.append(dict(member=name, sha256=hashlib.sha256(tar.extractfile(name).read()).hexdigest(),
                html_asset_id=asset(identity,basename + '.html',edition + ': ' + basename,'html'),
                source_asset_id=asset(identity + '_source',basename + '.source.txt',edition + ' original roff: ' + basename,'txt',True)))
            if basename == 'ssh_config.5':
                manuals[-1]['section_links'] = {'#TIME_FORMATS':{'target':'sshd_config.5.html#TIME_FORMATS','expected_count':3},
                    '#VERIFYING_HOST_KEYS':{'target':'ssh.1.html#VERIFYING_HOST_KEYS','expected_count':2}}
            elif basename == 'sshd_config.5':
                manuals[-1]['section_links'] = {'#PATTERNS':{'target':'ssh_config.5.html#PATTERNS','expected_count':1}}
        notice = dict(member='openssh-10.5p1/LICENCE',sha256=hashlib.sha256(tar.extractfile('openssh-10.5p1/LICENCE').read()).hexdigest(),
                      asset_id=asset('docs_openssh_105p1_licence','LICENCE.txt',edition + ' original release notice','txt',True))
    recipe = dict(id=recipe_id,resource_id='linux-programming-docs',adapter='mdoc',version='1',
        source_asset_ids=[source['id']],output_asset_ids=[a['id'] for a in assets],workspace_bytes=1024 * 1024,
        selection=dict(source_asset_id=source['id'],edition=edition,manuals=manuals,notice=notice,
                       renderer_probe_sha256=hashlib.sha256(_mandoc(PROBE,edition)).hexdigest()),
        review=dict(status='approved',evidence=evidence),blockers=[],metadata_sources=[])
    output.mkdir(parents=True)
    by_id = {a['id']:a for a in existing + assets}
    rendered = render(recipe,{source['id']:archive},by_id,output / 'rendered')
    for row in assets:
        row.update(size_bytes=rendered[row['id']].stat().st_size,sha256=sha256_file(rendered[row['id']]))
        destination = output / 'preview' / row['destination']
        destination.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(rendered[row['id']],destination)
    preview_source = output / 'preview' / source['destination']
    preview_source.parent.mkdir(parents=True,exist_ok=True)
    shutil.copyfile(archive,preview_source)
    prior_manifest = {row['path']:row for row in json.loads((evidence_dir/'openssh-direct.manifest.json').read_text())}
    body_reviews = []
    for manual in manuals:
        current = _body(rendered[manual['html_asset_id']])
        name = Path(manual['member']).name + '.html'
        previous = evidence_dir/'openssh-10.5p1-direct'/name
        matches = None
        if name in prior_manifest:
            pin = prior_manifest[name]
            if previous.stat().st_size != pin['bytes'] or sha256_file(previous) != pin['sha256']:
                raise ValueError('Previously reviewed rendered manual differs from its preserved evidence')
            matches = current == _body(previous)
            if not matches:
                raise ValueError('Complete manual body differs from the previously preserved rendering: ' + name)
        body_reviews.append(dict(asset_id=manual['html_asset_id'],**current,previous_render_text_matches=matches))
    resource = next(r for r in read_yaml(resources)['resources'] if r['id']=='linux-programming-docs')
    removed = [i for i in resource['asset_ids'] if i.startswith('docs_openssh_openbsd79_') or i=='docs_openssh_release_license']
    update = dict(id=resource['id'],status='partial',
        asset_ids=list(dict.fromkeys([i for i in resource['asset_ids'] if i not in removed] +
                                    [a['id'] for a in assets])),
        reason='Complete Python/SQLite packages, selected GNU/Linux/systemd manuals, and all 16 OpenSSH portable '
               '10.5p1 manuals are pinned with original sources and notices. The portable edition replaces the '
               'incomplete OpenBSD 7.9 default subset and covers ssh-keygen, sftp-server, ssh-keyscan and '
               'ssh-keysign. Cross-references outside selected release/manual scopes and intended-device '
               'verification remain open; the collection is partial.')
    fragment = dict(schema_version=1,assets=assets,acquisition_recipes=[recipe],resource_updates=[update],
        navigation_assignments=[dict(asset_id=m['html_asset_id'],topic_id='computing',purpose='reference') for m in manuals])
    portable = dict(schema_version=1,recipe_id=recipe_id,edition=edition,source_asset_id=source['id'],
        source_sha256=source['sha256'],source_size_bytes=source['size_bytes'],
        renderer_probe_sha256=recipe['selection']['renderer_probe_sha256'],
        renderer='mandoc HTML fragment, fixed edition/locale; exact output pins reject implementation drift',
        manual_count=len(manuals),output_count=len(assets),output_bytes=sum(a['size_bytes'] for a in assets),
        body_reviews=body_reviews,
        replaced_default_asset_ids=removed,manuals=manuals,notice=notice,
        outputs=[{k:a[k] for k in ('id','destination','size_bytes','sha256')} for a in assets],
        new_downloads=0,
        remaining_gaps=['Referenced platform/system manuals outside this release are explicitly listed on each page.',
                        'The former OpenBSD 7.9 edition remains incomplete and is not relabeled as portable 10.5p1.',
                        'Physical-device validation remains separate.'])
    atomic_write(output / 'fragment.json',(json.dumps(fragment,indent=2)+'\n').encode())
    atomic_write(output / 'evidence.json',(json.dumps(portable,indent=2)+'\n').encode())
    return dict(fragment=str(output/'fragment.json'),evidence=str(output/'evidence.json'),assets=len(assets),
                manuals=len(manuals),bytes=portable['output_bytes'],downloads=0)


def main(argv=None):
    root = Path(__file__).resolve().parents[3]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('evidence_dir',type=Path)
    parser.add_argument('output',type=Path)
    parser.add_argument('--catalog',type=Path,default=root/'catalog/library.yaml')
    parser.add_argument('--resources',type=Path,default=root/'catalog/resources.yaml')
    args = parser.parse_args(argv)
    print(json.dumps(prepare(args.evidence_dir,args.output,args.catalog,args.resources),sort_keys=True))
    return 0
