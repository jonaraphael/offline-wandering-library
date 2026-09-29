"""Write per-asset metadata for atlas fixtures."""
from collections import defaultdict
import yaml


def write_assignments(directory, rows):
    folder = directory / 'assignments'
    folder.mkdir(exist_ok=True)
    for path in folder.glob('*.yaml'):
        path.unlink()
    grouped = defaultdict(list)
    for row in rows:
        grouped[row['asset_id']].append({k: v for k, v in row.items() if k != 'asset_id'})
    for aid, entries in grouped.items():
        (folder / (aid + '.yaml')).write_text(yaml.safe_dump(
            {'schema_version': 1, 'asset_id': aid, 'assignments': entries}), encoding='utf-8')
