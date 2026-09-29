"""Validate practical coverage and priorities without file-count or byte quotas."""
import json
from pathlib import Path

from .catalog import CatalogError, capacity_plan, resolve_content

POLICY_PATH = Path(__file__).with_suffix('.json')


def require_utility_policy(assets, resources, profiles, resources_path):
    policy = json.loads(POLICY_PATH.read_text())
    verticals = json.loads(POLICY_PATH.with_name('topic_verticals.json').read_text())['verticals']
    known_domains = {d for vertical in verticals for d in vertical['domains']}
    for kind, rows in (('asset', assets), ('resource', resources.values())):
        for row in rows:
            if row.get('utility_tier') not in policy['tiers']:
                raise CatalogError(f"{kind} {row['id']}: missing or invalid utility_tier")
            if not isinstance(row.get('utility_reason'), str) or not row['utility_reason'].strip():
                raise CatalogError(f"{kind} {row['id']}: utility_reason is required")
            domains = row.get('knowledge_domains')
            if not isinstance(domains, list) or not domains or any(not isinstance(d, str) or not d.strip() for d in domains):
                raise CatalogError(f"{kind} {row['id']}: knowledge_domains must be nonempty strings")
            if set(domains) - known_domains:
                raise CatalogError(f"{kind} {row['id']}: unknown topic domains")
    by_id = {a['id']: a for a in assets}
    mapped = set()
    for resource in resources.values():
        ids = set(resource['asset_ids']).union(*(e['asset_ids'] for e in resource.get('editions', {}).values()))
        mapped.update(ids)
        if resource['target_bytes'] != sum(by_id[i]['size_bytes'] for i in resource['asset_ids']):
            raise CatalogError(f"{resource['id']}: collection size must equal its actual pinned files")
        if any(by_id[i]['utility_tier'] != resource['utility_tier'] for i in ids):
            raise CatalogError(f"{resource['id']}: split mixed priorities into separately selectable collections")
    if set(by_id) - mapped:
        raise CatalogError("Every selectable asset needs a collection")
    reports = []
    for profile in profiles.values():
        if not profile.get('default_resources') and not any(profile['id'] in a['profiles'] for a in assets):
            continue
        if any(key in profile for key in policy['forbidden_profile_quotas']):
            raise CatalogError(f"{profile['id']}: select domain coverage, not file-count or byte quotas")
        selected, unresolved, selection = resolve_content(assets, profile, resources_path=resources_path)
        if unresolved or (selection and selection['incomplete_resources']):
            raise CatalogError(f"{profile['id']}: default contains unavailable content")
        if any(a['utility_tier'] not in policy['default_tiers'] for a in selected):
            raise CatalogError(f"{profile['id']}: NONESSENTIAL content must be opt-in")
        domains = {d for a in selected for d in a['knowledge_domains']}
        missing = set(policy['required_default_domains']) - domains
        if missing:
            raise CatalogError(f"{profile['id']}: missing practical domains: {', '.join(sorted(missing))}")
        plan = capacity_plan(selected, profile, selection)
        if not plan['in_place_target_budget_fits']:
            raise CatalogError(f"{profile['id']}: default exceeds capacity including build workspace")
        reports.append({'profile':profile['id'], 'assets':len(selected), 'content_bytes':sum(a['size_bytes'] for a in selected),
                        'domains':sorted(domains), 'peak_bytes':plan['in_place_peak_budget_bytes']})
    return reports
