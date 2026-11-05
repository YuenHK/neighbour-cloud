"""Replay fixed synthetic range/vehicle faults. Never opens robot or camera I/O."""
import argparse
import csv
import json
from pathlib import Path

from edge_hub.navigation_scenarios import SCENARIOS, replay


def run(output):
    output.mkdir(parents=True, exist_ok=False)
    reports = [replay(name) for name in SCENARIOS]
    summaries = []
    for report in reports:
        trace = report.pop('trace')
        assert report['collisions'] == 0 and report['maximum_speed_mps'] <= .15
        assert report['execution_enabled'] is False and report['hardware_commands'] == 0
        if report['scenario'] == 'clear_route':
            assert report['final_state'] == 'arrived'
        else:
            assert 0 <= report['first_stop_ms']-report['injection_ms'] <= 100
            assert report['fully_stopped_ms']-report['first_stop_ms'] <= 300
        with (output/(report['scenario']+'.csv')).open('x', newline='', encoding='utf-8') as stream:
            writer = csv.DictWriter(stream, fieldnames=list(trace[0]))
            writer.writeheader()
            writer.writerows(trace)
        report['trace_csv'] = report['scenario']+'.csv'
        report['samples'] = len(trace)
        summaries.append(report)
    value = {'format': 'neighbour-offline-navigation-replay-v1', 'passed': True,
        'scenarios': summaries, 'camera_accuracy_tested': False, 'physical_stop_tested': False,
        'real_hardware_commands': 0, 'dependencies': 'Python standard library and bundled RouteFollower only'}
    with (output/'SUMMARY.json').open('x', encoding='utf-8') as stream:
        json.dump(value, stream, indent=2)
    return value


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    value = run(args.output)
    print(json.dumps({'passed': value['passed'], 'scenarios': len(value['scenarios']),
        'real_hardware_commands': 0, 'physical_stop_tested': False}))


if __name__ == '__main__':
    main()
