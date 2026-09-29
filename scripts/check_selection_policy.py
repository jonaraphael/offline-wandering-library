#!/usr/bin/env python3
"""Check every selectable file, collection priority and default practical coverage."""
import json
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'src'))
from owl.catalog import load_catalog, load_profiles
from owl.content_policy import require_content_policy
from owl.resources import load_resources
from owl.utility_policy import require_utility_policy

def main():
    try:
        profiles = load_profiles(ROOT/'profiles')
        assets = load_catalog(ROOT/'catalog/library.yaml', profiles)
        require_content_policy(assets)
        path = ROOT/'catalog/resources.yaml'
        resources = load_resources(path, assets)
        report = require_utility_policy(assets, resources, profiles, path)
        print(json.dumps({'compliant':True, 'selectable_assets':len(assets), 'profiles':report}, indent=2))
        return 0
    except (ValueError, OSError) as error:
        print(f'ERROR: {error}', file=sys.stderr)
        return 1

if __name__ == '__main__':
    raise SystemExit(main())
