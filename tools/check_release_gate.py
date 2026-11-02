"""Reject deployment without a fresh source-matching, full isolated acceptance.

Run this from the deployment preparation command. It never deploys, accesses
credentials, starts native services, or consumes hosted CI minutes.
"""
import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.acceptance_gate import fingerprint


def require_acceptance(root, receipt):
    value = json.loads(Path(receipt).read_text(encoding='utf-8'))
    if (value.get('passed') is not True or value.get('source_unchanged_during_checks') is not True
            or value.get('source_sha256') != fingerprint(Path(root))
            or not 0 <= time.time() - value.get('completed_at', 0) <= 86400
            or len(value.get('checks', [])) != 5 or any(row['exit'] != 0 for row in value['checks'])):
        raise ValueError('fresh_source_matching_acceptance_required')
    return {'accepted': True, 'source_sha256': value['source_sha256'], 'deploy_permission': False}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('receipt')
    args = parser.parse_args()
    print(json.dumps(require_acceptance(Path(__file__).resolve().parents[1], args.receipt)))
