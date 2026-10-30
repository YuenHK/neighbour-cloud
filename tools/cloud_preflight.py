"""Read-only cloud-host readiness checks. No network, app imports or DB writes."""
import argparse
import importlib.metadata
import json
import platform
from pathlib import Path

from local_audio_gateway.model_paths import SENSEVOICE_DIRECTORY


def report(root, settings, model, *, system=None, python=None):
    root, settings, model = Path(root), Path(settings), Path(model)
    checks = []

    def check(name, passed, purpose):
        checks.append({'id': name, 'passed': passed is True, 'purpose': purpose})

    check('linux_host', (system or platform.system()) == 'Linux', 'actual cloud Linux host')
    version = python or platform.python_version_tuple()
    check('python_312', tuple(version[:2]) == ('3', '12'), 'supported interpreter')
    check('hub_source', (root / 'edge_hub/app.py').is_file(), 'resident and staff backend')
    check('airi_build', all((root / '.vendor/airi/apps/stage-web/dist' / path).is_file()
                          for path in ('index.html', 'ui/estate-resident-entry.html',
                                       'ui/estate-settings-entry.html')), 'built avatar and settings')
    check('airi_runtime', (root / '.vendor/airi/packages/server-runtime/dist/bin/run.mjs').is_file(),
          'AIRI WebSocket runtime; Node dependencies require a separate install check')
    check('sensevoice_assets', all((model / name).is_file() and (model / name).stat().st_size > 0
                                  for name in ('model.int8.onnx', 'tokens.txt')),
          'Cantonese ASR assets; recognition requires a separate acceptance test')
    requirements = {}
    for module in ('fastapi', 'httpx', 'onnxruntime', 'bm25s', 'sherpa-onnx', 'av'):
        try:
            requirements[module] = importlib.metadata.version(module)
        except importlib.metadata.PackageNotFoundError:
            requirements[module] = None
    check('python_packages', all(requirements.values()), 'backend and ASR dependencies installed')
    # An operator-produced migration receipt is required; a blank cloud DB or
    # reset counters cannot be accepted as an automatic successful migration.
    try:
        receipt = json.loads((settings / 'cloud-cutover-receipt.json').read_text(encoding='utf-8'))
        safe = (receipt.get('format') == 'neighbour-cloud-cutover-v1'
                and receipt.get('source_writers_stopped') is True
                and receipt.get('usage_counters_preserved') is True
                and receipt.get('retention_receipts_preserved') is True
                and receipt.get('restored_and_verified') is True)
    except (OSError, ValueError, AttributeError):
        safe = False
    check('verified_data_cutover', safe, 'one writer and preserved quotas/retention/history')
    check('manual_ep_only', (root / '.runtime/ep-manual-operation.json').is_file(),
          'cloud boot must not discover or connect local robots')
    return {'ready_for_host_acceptance': all(item['passed'] for item in checks),
            'publicly_deployed': False, 'checks': checks, 'packages': requirements,
            'not_verified': ['HTTPS owner login', 'service restart/restore', 'voice and conversation',
                             'Notebook powered-off acceptance', 'persistent disk durability']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--settings', type=Path, required=True)
    parser.add_argument('--model', type=Path, default=Path('models/speech') / SENSEVOICE_DIRECTORY)
    args = parser.parse_args()
    result = report(args.root, args.settings, args.model)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(0 if result['ready_for_host_acceptance'] else 2)


if __name__ == '__main__':
    main()
