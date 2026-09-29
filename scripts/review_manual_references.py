#!/usr/bin/env python3
"""Apply exact-pin reference classifications to an existing whole-package audit.

No content download, modification, admission, or automatic subject judgment.
Only reviewed publisher-feedback anchors can be optional; runtime dependencies
and reading references remain required. Original failures stay in the audit.
"""
import argparse
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from owl.acquisition.supervisor import read,save,digest
from owl.safety import SafetyError,sha256_file


def classify(audit,policy,*,audit_sha256):
    if (policy.get('schema_version')!=1 or policy.get('audit_sha256')!=audit_sha256
            or policy.get('source_sha256')!=audit.get('source_sha256')
            or audit.get('whole_package_preserved') is not True):
        raise SafetyError('Reference policy must bind the complete preserved package audit')
    rules=policy.get('references',[])
    if not 1<=len(rules)<=20:raise SafetyError('Require1–20 explicitly reviewed references')
    members={m['path']:m for m in audit['members']};counts=[0]*len(rules)
    for rule in rules:
        if (rule.get('classification')!='optional_publisher_feedback' or rule.get('tag')!='a'
                or rule.get('attribute')!='href' or not rule.get('reason') or rule.get('expected_count')!=1
                or members.get(rule.get('document'),{}).get('original_sha256')!=rule.get('source_member_sha256')):
            raise SafetyError('Optional policy needs an exact pinned feedback anchor and rationale')
    required,optional=[],[]
    for row in audit['missing_local_links']:
        matches=[i for i,r in enumerate(rules) if all(row.get(k)==r.get(k) for k in ('document','tag','attribute','url'))]
        if len(matches)>1:raise SafetyError('Ambiguous reference classifications')
        if matches:
            i=matches[0]
            if row.get('kind')!='cross-reference':raise SafetyError('Runtime dependency cannot become optional feedback')
            counts[i]+=1;optional.append({**row,'classification':rules[i]['classification'],'reason':rules[i]['reason']})
        else:required.append(row)
    if counts!=[r['expected_count'] for r in rules]:raise SafetyError('Reviewed reference membership or occurrence count changed')
    return {'schema_version':1,'content_ready':False,'status':'references_classified_awaiting_review',
        'audit_sha256':audit_sha256,'policy_sha256':digest(policy),'source_sha256':audit['source_sha256'],
        'members_verified':audit['members_verified'],'whole_package_preserved':True,
        'missing_essential_local_links':required,'optional_publisher_feedback':optional,
        'scope':'Reference classification only; browser and substantive content review remain required.'}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ['audit','policy','output']:p.add_argument('--'+name,type=Path,required=True)
    a=p.parse_args();result=classify(read(a.audit,64*1024*1024),read(a.policy),audit_sha256=sha256_file(a.audit))
    if a.output.exists() and read(a.output)!=result:raise SafetyError('Classified evidence changed; use a new version')
    save(a.output,result)
    print(json.dumps({'content_ready':False,'missing_essential_links':len(result['missing_essential_local_links']),
        'optional_feedback':len(result['optional_publisher_feedback']),'detail':str(a.output)}))


if __name__=='__main__':main()
