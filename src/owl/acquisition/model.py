"""Validation shared by acquisition tooling and normal build integration."""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import re
from urllib.parse import urlsplit

from ..catalog import CatalogError, read_yaml


class AcquisitionError(CatalogError):
    pass


def input_asset_ids(recipe):
    notices = [identity for source in recipe.get('build_inputs', []) for identity in source.get('notice_asset_ids', [])]
    return list(dict.fromkeys([*recipe['source_asset_ids'], *recipe_build_inputs(recipe),
                              *recipe.get('dependency_asset_ids', []), *notices]))


def recipe_build_inputs(recipe):
    return {source['id']: source for source in recipe.get('build_inputs', [])}


def build_input_metadata_allowance(recipe):
    # Owned download metadata plus bounded 7z owner and member receipts. These
    # small records survive source cleanup and are separate from library books.
    return (65536 if recipe.get('build_inputs') else 0) + 131072 * len(recipe.get('build_input_extractions',[]))


def build_input_assets(recipes):
    result = {identity: {'category':'reference', 'redistributable':False, 'supporting_file':True,
                       'required':True, 'profiles':[], **source}
            for identity, source in build_inputs(recipes).items()}
    for extraction in build_input_extractions(recipes).values():
        original = result[extraction['source_id']]
        for member in extraction['members']:
            derived = {**original, **{key:member[key] for key in ('id','size_bytes','sha256')},
                'title': original['title'] + ': ' + member['path'],
                'format': Path(member['path']).suffix.lstrip('.').lower(),
                'build_archive_source_id': original['id']}
            if member['id'] in result and result[member['id']] != derived:
                raise AcquisitionError('Conflicting raw/extracted build-input identity')
            result[member['id']] = derived
    return result


def build_input_extractions(recipes):
    rows = recipes.values() if isinstance(recipes,dict) else recipes
    result = {}
    for recipe in rows:
        for extraction in recipe.get('build_input_extractions',[]):
            sid = extraction['source_id']
            if sid not in result:
                result[sid] = deepcopy(extraction)
                continue
            current = result[sid]
            by_id = {member['id']:member for member in current['members']}
            paths = {member['path']:member for member in current['members']}
            for member in extraction['members']:
                if (member['id'] in by_id and by_id[member['id']] != member or
                        member['path'] in paths and paths[member['path']] != member):
                    raise AcquisitionError('Conflicting shared build-input extraction member')
                if member['id'] not in by_id:
                    current['members'].append(member)
                    by_id[member['id']] = member
                    paths[member['path']] = member
            current['max_bytes'] = max(current['max_bytes'],extraction['max_bytes'])
            current['max_files'] = max(current['max_files'],extraction['max_files'])
            if 'timeout_seconds' in current or 'timeout_seconds' in extraction:
                current['timeout_seconds'] = max(current.get('timeout_seconds',3600),extraction.get('timeout_seconds',3600))
    return result


def retained_input_asset_ids(recipe):
    transient = build_input_assets([recipe])
    return [identity for identity in input_asset_ids(recipe) if identity not in transient]


def build_inputs(recipes):
    """Unique temporary source records; conflicting shared pins are an error."""
    rows = recipes.values() if isinstance(recipes, dict) else recipes
    result = {}
    for recipe in rows:
        for identity, source in recipe_build_inputs(recipe).items():
            if identity in result and result[identity] != source:
                raise AcquisitionError(f'Conflicting shared build input: {identity}')
            result[identity] = source
    return result


def _strings(value, label, *, identifiers=False):
    if (not isinstance(value, list) or any(not isinstance(x, str) or not x.strip() for x in value)
            or len(set(value)) != len(value)):
        raise AcquisitionError(f"{label}: expected unique nonempty strings")
    if identifiers and any(not re.fullmatch(r"[a-z0-9][a-z0-9_-]*", x) for x in value):
        raise AcquisitionError(f"{label}: invalid identifier")
    return value


def validate_recipes(document, *, assets=None, require_approved=False, allow_local=False):
    if isinstance(document, dict):
        if type(document.get("schema_version")) is not int or document["schema_version"] != 1:
            raise AcquisitionError("Recipes require schema_version: 1")
        rows = document.get("recipes", document.get("acquisition_recipes"))
    else:
        rows = document
    if not isinstance(rows, list):
        raise AcquisitionError("Recipes require a recipes list")
    result = {}
    asset_map = None if assets is None else (assets if isinstance(assets, dict) else {a["id"]: a for a in assets})
    required = {"id", "resource_id", "adapter", "version", "source_asset_ids", "output_asset_ids", "selection", "review", "blockers"}
    for raw in rows:
        if not isinstance(raw, dict) or required - raw.keys():
            raise AcquisitionError("Recipe is missing required fields")
        row = deepcopy(raw)
        for field in ("id", "resource_id", "adapter"):
            if not isinstance(row[field], str) or not re.fullmatch(r"[a-z0-9][a-z0-9_-]*", row[field]):
                raise AcquisitionError(f"Recipe {field}: invalid identifier")
        rid = row["id"]
        if rid in result:
            raise AcquisitionError(f"Duplicate recipe id: {rid}")
        if not isinstance(row["version"], str) or not row["version"].strip():
            raise AcquisitionError(f"{rid}: version must be nonempty text")
        for field in ("source_asset_ids", "output_asset_ids"):
            _strings(row[field], f"{rid}.{field}", identifiers=True)
        temporary = row.get('build_inputs', [])
        if not isinstance(temporary, list):
            raise AcquisitionError(f'{rid}: build_inputs must be a list of pinned records')
        extractions = row.get('build_input_extractions',[])
        if not isinstance(extractions,list):
            raise AcquisitionError(f'{rid}: build_input_extractions must be a list')
        extraction_sources, extracted_ids = set(), set()
        from ..safety import validate_relative
        for extraction in extractions:
            required_extraction={'source_id','format','max_bytes','max_files','members'}
            if (not isinstance(extraction,dict) or not required_extraction <= set(extraction) or
                    set(extraction) - required_extraction - {'timeout_seconds'} or
                    extraction['format'] != '7z' or type(extraction['max_bytes']) is not int or extraction['max_bytes']<=0 or
                    type(extraction['max_files']) is not int or not 1<=extraction['max_files']<=100000 or
                    not isinstance(extraction['members'],list) or not extraction['members']):
                raise AcquisitionError(f'{rid}: invalid bounded 7z extraction declaration')
            if (type(extraction.get('timeout_seconds',3600)) is not int or
                    not 1 <= extraction.get('timeout_seconds',3600) <= 3600):
                raise AcquisitionError(f'{rid}: extraction timeout_seconds must be between 1 and 3600')
            _strings([extraction['source_id']],f'{rid}.extraction.source_id',identifiers=True)
            if extraction['source_id'] in extraction_sources:
                raise AcquisitionError(f'{rid}: duplicate extraction source')
            extraction_sources.add(extraction['source_id'])
            names=set()
            for member in extraction['members']:
                if not isinstance(member,dict) or set(member) != {'id','path','size_bytes','sha256'}:
                    raise AcquisitionError(f'{rid}: extracted member needs id/path/size_bytes/sha256')
                _strings([member['id']],f'{rid}.member.id',identifiers=True)
                validate_relative(member['path'])
                if (member['id'] in extracted_ids or member['id'] not in row['source_asset_ids'] or
                        (asset_map is not None and member['id'] in asset_map) or member['path'].casefold() in names):
                    raise AcquisitionError(f'{rid}: duplicate, unused or retained extraction member')
                if (type(member['size_bytes']) is not int or member['size_bytes']<=0 or
                        not isinstance(member['sha256'],str) or not re.fullmatch('[0-9a-f]{64}',member['sha256'])):
                    raise AcquisitionError(f'{rid}: extracted member must have positive bytes and whole-file SHA-256')
                extracted_ids.add(member['id']);names.add(member['path'].casefold())
            if (sum(member['size_bytes'] for member in extraction['members'])>extraction['max_bytes'] or
                    len(extraction['members'])>extraction['max_files']):
                raise AcquisitionError(f'{rid}: extracted members exceed their declared limits')
        seen_inputs = set()
        for source in temporary:
            required_source = {'id', 'title', 'format', 'source_url', 'version', 'size_bytes', 'sha256', 'license', 'notice_asset_ids'}
            allowed_source = required_source | {'publisher', 'source_page', 'attribution', 'language', 'mirrors', 'source_resource_ids'}
            if not isinstance(source, dict) or not required_source <= source.keys() or source.keys() - allowed_source:
                raise AcquisitionError(f'{rid}: build input requires explicit pins and retained notice_asset_ids; no final destination')
            sid = source['id']
            _strings([sid], f'{rid}.build_inputs.id', identifiers=True)
            if (sid in seen_inputs or sid in extracted_ids or (sid not in row['source_asset_ids'] and sid not in extraction_sources)
                    or sid in row['output_asset_ids']):
                raise AcquisitionError(f'{rid}: duplicate, unused or overlapping build input {sid}')
            seen_inputs.add(sid)
            if asset_map is not None and sid in asset_map:
                raise AcquisitionError(f'{rid}: build input {sid} also appears as a retained catalog asset')
            if (type(source['size_bytes']) is not int or source['size_bytes'] <= 0 or
                    not isinstance(source['sha256'], str) or not re.fullmatch(r'[0-9a-f]{64}',source['sha256'])):
                raise AcquisitionError(f'{rid}: build input {sid} needs a positive size and complete SHA-256 pin')
            for key in ('title','format','version','license'):
                if not isinstance(source[key],str) or not source[key].strip():
                    raise AcquisitionError(f'{rid}: build input {sid} requires {key}')
            _strings(source['notice_asset_ids'],f'{rid}.{sid}.notice_asset_ids',identifiers=True)
            _strings(source.get('source_resource_ids',[]),f'{rid}.{sid}.source_resource_ids',identifiers=True)
            _strings(source.get('mirrors',[]),f'{rid}.{sid}.mirrors')
            for value in [source['source_url'],*source.get('mirrors',[])]:
                url = urlsplit(value) if isinstance(value,str) else None
                allowed = {'https','file','repo','http'} if allow_local else {'https'}
                if (not url or url.scheme not in allowed or url.username or url.password or url.fragment or
                        (url.scheme in {'http','https'} and not url.hostname)):
                    raise AcquisitionError(f'{rid}: build input {sid} needs HTTPS (local fixtures require allow_local)')
        if not extraction_sources <= seen_inputs:
            raise AcquisitionError(f'{rid}: extraction archive must be an explicit pinned build input')
        _strings(row.get("dependency_asset_ids", []), f"{rid}.dependency_asset_ids", identifiers=True)
        if set(input_asset_ids(row)) & set(row["output_asset_ids"]):
            raise AcquisitionError(f"{rid}: source and output IDs overlap")
        if not isinstance(row["selection"], dict):
            raise AcquisitionError(f"{rid}: selection must be a mapping")
        if "work_ids" in row["selection"]:
            _strings(row["selection"]["work_ids"], f"{rid}.selection.work_ids")
        if "workspace_bytes" in row and (type(row["workspace_bytes"]) is not int or row["workspace_bytes"] < 0):
            raise AcquisitionError(f"{rid}: workspace_bytes must be a nonnegative integer")
        review = row["review"]
        if (not isinstance(review, dict) or set(review) != {"status", "evidence"}
                or review["status"] not in {"pending", "approved"}):
            raise AcquisitionError(f"{rid}: review needs status and evidence")
        _strings(review["evidence"], f"{rid}.review.evidence")
        _strings(row["blockers"], f"{rid}.blockers")
        sources = row.setdefault("metadata_sources", [])
        if not isinstance(sources, list):
            raise AcquisitionError(f"{rid}: metadata_sources must be a list")
        for source in sources:
            if not isinstance(source, dict) or not {"url", "kind"} <= source.keys():
                raise AcquisitionError(f"{rid}: metadata source needs url and kind")
            url = urlsplit(source["url"]) if isinstance(source["url"], str) else None
            if (not url or url.scheme != "https" or not url.hostname or url.username or url.password or url.fragment
                    or not isinstance(source["kind"], str) or not source["kind"]):
                raise AcquisitionError(f"{rid}: invalid HTTPS metadata source")
        if require_approved and review["status"] != "approved":
            raise AcquisitionError(f"{rid}: recipe is not approved")
        if row["adapter"] == "epub_pdf":
            from .epub_pdf import validate_recipe
            validate_recipe(row, None if asset_map is None else {**asset_map, **build_input_assets([row])})
        if row["adapter"] == "zip_localized":
            from .zip_localized import validate_recipe
            validate_recipe(row, None if asset_map is None else {**asset_map, **build_input_assets([row])})
        if review["status"] == "approved":
            if row['resource_id'] in {'books-culture-expansion', 'complete-courses-expansion'} and not row['selection'].get('work_ids'):
                raise AcquisitionError(f'{rid}: approved expansion recipes require stable whole-work IDs for deduplication')
            if not review["evidence"] or row["blockers"] or not row["source_asset_ids"] or not row["output_asset_ids"]:
                raise AcquisitionError(f"{rid}: approved recipe needs sources, outputs, evidence and no blockers")
            if asset_map is not None:
                for sid in input_asset_ids(row):
                    source = build_input_assets([row]).get(sid, asset_map.get(sid, {}))
                    if (source.get("status", "resolved") != "resolved" or not isinstance(source.get("sha256"), str)
                            or not re.fullmatch(r"[0-9a-f]{64}", source["sha256"])
                            or type(source.get("size_bytes")) is not int or source["size_bytes"] <= 0):
                        raise AcquisitionError(f"{rid}: source {sid} is not resolved and pinned")
        result[rid] = row
    temporary = build_inputs(result)
    virtual = build_input_assets(result)
    sizes = {}
    for source in temporary.values():
        if source['sha256'] in sizes and sizes[source['sha256']] != source['size_bytes']:
            raise AcquisitionError('One build-input SHA-256 has conflicting byte sizes')
        sizes[source['sha256']] = source['size_bytes']
        if set(source['notice_asset_ids']) & set(virtual):
            raise AcquisitionError('Build-input notices must remain retained catalog assets')
    return result


def load_recipes(path: Path):
    return validate_recipes(read_yaml(path))


def validate_generation(assets, recipes, *, allow_local=False):
    """Generated catalog records can only reference complete, approved recipes."""
    rows = list(recipes.values()) if isinstance(recipes, dict) else recipes
    recipes = validate_recipes(rows, assets=assets, allow_local=allow_local)
    by_id = {a["id"]: a for a in assets}
    for asset in assets:
        generation = asset.get("generation")
        if generation is None:
            continue
        if "archive_member" in asset:
            raise AcquisitionError(f"{asset['id']}: archive_member and generation cannot coexist")
        if (not isinstance(generation, dict) or "recipe_id" not in generation
                or set(generation) - {"recipe_id", "question_id", "lesson_id", "output_id"}
                or any(not isinstance(value, (str, int)) or isinstance(value, bool) for value in generation.values())):
            raise AcquisitionError(f"{asset['id']}: generation requires recipe_id")
        recipe = recipes.get(generation["recipe_id"])
        if not recipe or recipe["review"]["status"] != "approved" or asset["id"] not in recipe["output_asset_ids"]:
            raise AcquisitionError(f"{asset['id']}: generation requires an approved recipe listing this output")
        if (asset.get("status", "resolved") != "resolved" or not isinstance(asset.get("sha256"), str)
                or not re.fullmatch(r"[0-9a-f]{64}", asset["sha256"])):
            raise AcquisitionError(f"{asset['id']}: generated output must be resolved and pinned")
    for recipe in recipes.values():
        if recipe["review"]["status"] != "approved":
            continue
        for oid in recipe["output_asset_ids"]:
            if by_id.get(oid, {}).get("generation", {}).get("recipe_id") != recipe["id"]:
                raise AcquisitionError(f"{recipe['id']}: output {oid} is missing or has a different recipe")
    visiting, complete = set(), set()
    def visit(identity):
        if identity in complete:
            return
        if identity in visiting:
            raise AcquisitionError("Cycle in acquisition recipe dependencies")
        visiting.add(identity)
        for source_id in input_asset_ids(recipes[identity]):
            parent = by_id.get(source_id, {}).get("generation", {}).get("recipe_id")
            if parent is not None:
                visit(parent)
        visiting.remove(identity)
        complete.add(identity)
    for identity, recipe in recipes.items():
        if recipe["review"]["status"] == "approved":
            visit(identity)
