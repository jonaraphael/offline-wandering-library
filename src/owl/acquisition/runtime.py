"""Execute reviewed, pinned recipes only inside the normal locked build.

There is no shell, plugin loading, or network access in a renderer. Inputs are
ordinary catalog downloads; outputs must match their independently reviewed pins.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

from ..catalog import CatalogError
from ..download import verified
from ..safety import SafetyError, atomic_write, safe_path, reject_symlinks, sha256_file
from .model import input_asset_ids, retained_input_asset_ids, build_input_assets, build_input_metadata_allowance


ADAPTERS = {"html_snapshot", "manual_html", "mdoc", "stackexchange", "lessons", "zim_direct", "epub_pdf", "ocw_package", "zip_localized"}


def preflight_recipes(recipes: dict) -> None:
    """Check local generation dependencies before the build acquires bodies."""
    for recipe in recipes.values():
        if recipe.get('build_input_extractions'):
            from .sevenzip import preflight
            preflight()
        if recipe['adapter'] == 'mdoc':
            from .mdoc import preflight
            preflight(recipe)
        elif recipe['adapter'] == 'epub_pdf':
            from .epub_pdf import preflight
            preflight(recipe)


def recipe_digest(recipe: dict, assets=None) -> str:
    identity = recipe
    if assets is not None:
        by_id = {**(assets if isinstance(assets, dict) else {asset['id']: asset for asset in assets}),
                 **build_input_assets([recipe])}
        fields = ('id', 'sha256', 'size_bytes', 'destination', 'source_url', 'version',
                  'license', 'attribution', 'publisher', 'source_page', 'language')
        sources = []
        for source_id in input_asset_ids(recipe):
            if source_id not in by_id:
                raise CatalogError(f'Missing pinned recipe source: {source_id}')
            sources.append({key: by_id[source_id].get(key) for key in fields})
        identity = {'recipe': recipe, 'source_pins': sources}
    return hashlib.sha256(json.dumps(identity, sort_keys=True, separators=(",", ":"),
                                    ensure_ascii=False).encode()).hexdigest()


def selected_recipes(assets: list[dict], recipes: dict) -> dict:
    ids = {a['id'] for a in assets}
    needed = {a['generation']['recipe_id'] for a in assets if 'generation' in a}
    result = {}
    for identity in sorted(needed):
        recipe = recipes.get(identity)
        if recipe is None or recipe.get('adapter') not in ADAPTERS:
            raise CatalogError(f'Unsupported acquisition recipe: {identity}')
        if not set(retained_input_asset_ids(recipe)) <= ids:
            raise CatalogError(f'{identity}: select all pinned generation sources')
        if not set(recipe['output_asset_ids']) <= ids:
            raise CatalogError(f'{identity}: select the complete reviewed output edition')
        workspace = recipe.get('workspace_bytes', 0)
        if type(workspace) is not int or workspace < 0:
            raise CatalogError(f'{identity}: workspace_bytes must be a nonnegative integer')
        if recipe['adapter'] == 'stackexchange' and workspace <= 0:
            raise CatalogError(f'{identity}: corpus generation requires an explicit workspace allowance')
        result[identity] = recipe
    sources = {**{asset['id']: asset for asset in assets}, **build_input_assets(result)}
    selected_works = {}
    for identity, recipe in result.items():
        keys = [('work', work) for work in recipe['selection'].get('work_ids', [])]
        if recipe['adapter'] == 'zim_direct':
            source_id = recipe['selection'].get('source_asset_id')
            source_pin = sources.get(source_id, {}).get('sha256', source_id)
            keys.extend(('zim-entry', source_pin, entry) for entry in recipe['selection'].get('entries', []))
        for key in keys:
            if key in selected_works:
                raise CatalogError(f'Duplicate selected work in {selected_works[key]} and {identity}: {key[-1]}')
            selected_works[key] = identity
    return result


def order_assets(assets: list[dict], recipes: dict) -> list[dict]:
    """Dependency ordering includes archive sources and rejects cycles/missing inputs."""
    by_id = {a['id']: a for a in assets}
    output, visiting, emitted = [], set(), set()
    def visit(identity):
        if identity in emitted:
            return
        if identity in visiting:
            raise CatalogError('Cycle in acquisition/ZIP dependencies')
        if identity not in by_id:
            raise CatalogError(f'Missing acquisition dependency: {identity}')
        visiting.add(identity)
        asset = by_id[identity]
        if 'generation' in asset:
            for source in retained_input_asset_ids(recipes[asset['generation']['recipe_id']]):
                visit(source)
        if 'archive_member' in asset:
            visit(asset['archive_member']['source_asset_id'])
        visiting.remove(identity)
        emitted.add(identity)
        output.append(asset)
    for asset in assets:
        visit(asset['id'])
    return output


def allocation(recipes: dict, assets: list[dict] = ()) -> int:
    # Keep private work and receipts after interruption without hiding them from
    # nominal drive capacity. Outputs themselves are already catalog assets.
    by_id = {a['id']: a for a in assets}
    return sum(r.get('workspace_bytes', 0) + 65536 + build_input_metadata_allowance(r) +
               sum(by_id[i]['size_bytes'] for i in r['output_asset_ids'] if i in by_id)
               for r in recipes.values())


def directory_bytes(root: Path) -> int:
    reject_symlinks(root)
    total = 0
    if root.exists():
        for path in root.rglob('*'):
            reject_symlinks(path)
            if path.is_file():
                total += path.stat().st_size
    return total


class Generator:
    def __init__(self, target: Path, assets: list[dict], recipes: dict, progress=print, *, source_paths=None):
        self.target = target
        self.assets = {**{a['id']: a for a in assets}, **build_input_assets(recipes)}
        self.source_paths = source_paths or {}
        self.recipes = recipes
        self.progress = progress
        self.ready = {}

    def _render(self, recipe, sources, folder):
        adapter = recipe['adapter']
        if adapter in {'html_snapshot', 'manual_html'}:
            from .documents import render
        elif adapter == 'mdoc':
            from .mdoc import render
        elif adapter == 'stackexchange':
            from .corpus import render
        elif adapter == 'lessons':
            from .lessons import render
        elif adapter == 'epub_pdf':
            from .epub_pdf import render
        elif adapter == 'ocw_package':
            from .ocw_package import render
        elif adapter == 'zip_localized':
            from .zip_localized import render
        else:
            return self._zim(recipe, sources, folder)
        return render(recipe, sources, self.assets, folder)

    def _zim(self, recipe, sources, folder):
        from ..export_direct import export_zim
        source_id = recipe['selection']['source_asset_id']
        selection = recipe['selection']
        expected = selection['output_paths']
        if set(expected) != set(recipe['output_asset_ids']):
            raise CatalogError('ZIM recipe must map every reviewed output path')
        if any(self.assets[identity]['destination'] != path for identity, path in expected.items()):
            raise CatalogError('ZIM generated destinations must preserve reviewed export paths and relative links')
        report = export_zim(sources[source_id], folder / 'export',
            source_asset=self.assets[source_id], entries=selection['entries'],
            max_bytes=sum(self.assets[i]['size_bytes'] for i in expected),
            max_files=len(expected), max_item_bytes=selection.get('max_item_bytes', 16 * 1024 * 1024),
            export_id=recipe['id'], progress=self.progress,
            _held_build_root=self.target)
        actual = {a['destination']: a for a in report['assets']}
        if set(actual) != set(expected.values()) or report.get('requires_review'):
            raise SafetyError('Direct export differs from its reviewed file/dependency selection')
        return {identity: safe_path(folder / 'export/LIBRARY', path)
                for identity, path in expected.items()}

    def materialize(self, asset: dict, destination: Path) -> str:
        recipe = self.recipes[asset['generation']['recipe_id']]
        digest = recipe_digest(recipe, self.assets)
        folder = safe_path(self.target, '.owl/acquisition/' + recipe['id'])
        marker = safe_path(folder, 'owner.json')
        owner = {'owner': 'owl-acquisition', 'recipe_sha256': digest}
        if folder.exists():
            if (not marker.is_file() or marker.stat().st_size > 4096 or
                    json.loads(marker.read_text(encoding='utf-8')) != owner):
                raise SafetyError('Acquisition workspace belongs to a different recipe; use a new recipe ID')
        else:
            folder.mkdir(parents=True)
            atomic_write(marker, json.dumps(owner, sort_keys=True).encode())
        receipt = safe_path(folder, 'outputs.json')
        if recipe['id'] not in self.ready:
            sources = {}
            for identity in input_asset_ids(recipe):
                source = self.assets[identity]
                path = self.source_paths.get(identity)
                if path is None:
                    if 'destination' not in source:
                        raise SafetyError(f'Missing verified build-only source: {identity}')
                    path = safe_path(self.target, source['destination'])
                if not verified(path, source['size_bytes'], source['sha256']):
                    raise SafetyError(f'Generation source hash/size mismatch: {identity}')
                if identity in recipe['source_asset_ids']:
                    sources[identity] = path
            saved = None
            if receipt.is_file() and receipt.stat().st_size <= 16 * 1024 * 1024:
                saved = json.loads(receipt.read_text(encoding='utf-8'))
            expected_ids = set(recipe['output_asset_ids'])
            paths = {}
            if isinstance(saved, dict) and set(saved) == expected_ids:
                for identity, relative in saved.items():
                    candidate = safe_path(folder, relative)
                    output = self.assets[identity]
                    final = safe_path(self.target, output['destination'])
                    if not (verified(candidate, output['size_bytes'], output['sha256']) or
                            verified(final, output['size_bytes'], output['sha256'])):
                        break
                    paths[identity] = candidate
            if set(paths) != expected_ids:
                self.progress(f"GENERATE {recipe['id']}: {len(expected_ids)} reviewed outputs")
                paths = self._render(recipe, sources, folder)
                if set(paths) != expected_ids:
                    raise SafetyError('Renderer output inventory differs from its reviewed recipe')
                relative = {}
                for identity, path in paths.items():
                    path = Path(path)
                    if not path.is_relative_to(folder):
                        raise SafetyError('Renderer wrote outside its owned acquisition workspace')
                    reject_symlinks(path)
                    output = self.assets[identity]
                    if not verified(path, output['size_bytes'], output['sha256']):
                        raise SafetyError(f'Generated output SHA-256/size mismatch: {identity}')
                    relative[identity] = path.relative_to(folder).as_posix()
                limit = sum(self.assets[i]['size_bytes'] for i in expected_ids) + recipe.get('workspace_bytes', 0) + 65536
                if directory_bytes(folder) > limit:
                    raise SafetyError('Acquisition workspace exceeds recipe allowance')
                atomic_write(receipt, json.dumps(relative, sort_keys=True).encode())
            self.ready[recipe['id']] = paths
        output = self.ready[recipe['id']][asset['id']]
        if not verified(output, asset['size_bytes'], asset['sha256']):
            raise SafetyError(f'Generated output changed before publication: {asset["id"]}')
        destination.parent.mkdir(parents=True, exist_ok=True)
        reject_symlinks(destination)
        os.replace(output, destination)
        return asset['sha256']
