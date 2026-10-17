#!/usr/bin/env python3
"""Read-only configuration validation; Docker containers use --rm and no data volumes."""
import json
from pathlib import Path
import subprocess
import tempfile
import yaml

ROOT = Path(__file__).resolve().parents[1]

def run(*args):
    subprocess.run(args, cwd=ROOT, check=True)

def main():
    run('python3', '-m', 'unittest', 'discover', '-s', 'tests', '-v')
    run('docker', 'compose', 'config', '--quiet')
    run('docker', 'run', '--rm', '--entrypoint', '/bin/promtool', '-v',
        f'{ROOT}/prometheus:/etc/prometheus:ro', 'prom/prometheus:latest',
        'check', 'config', '/etc/prometheus/prometheus.yml')
    expressions = []
    for path in (ROOT/'grafana/dashboards').glob('*.json'):
        for panel in json.loads(path.read_text())['panels']:
            expressions.extend(t['expr'] for t in panel['targets'])
    alerts = yaml.safe_load((ROOT/'grafana/provisioning/alerting/alerts.yml').read_text())
    rules = alerts['groups'][0]['rules']
    expressions.extend(r['data'][0]['model']['expr'] for r in rules)
    with tempfile.TemporaryDirectory(prefix='monitoring-validation-') as tmp:
        path = Path(tmp)
        path.chmod(0o755)
        recording_rules = {'groups': [{'name': 'expression-validation', 'rules': [
            {'record': f'validation:expression_{i}', 'expr': expr}
            for i, expr in enumerate(expressions)]}]}
        (path/'expressions.yml').write_text(yaml.safe_dump(recording_rules))
        run('docker', 'run', '--rm', '--entrypoint', '/bin/promtool', '-v',
            f'{tmp}:/validation:ro', 'prom/prometheus:latest',
            'check', 'rules', '/validation/expressions.yml')
        # Exercise actual Grafana expressions and thresholds using synthetic series.
        derived = []
        for rule in rules:
            threshold = rule['data'][1]['model']['conditions'][0]['evaluator']['params'][0]
            derived.append(dict(alert=rule['uid'], expr=f"({rule['data'][0]['model']['expr']}) > {threshold}",
                                **{'for': rule['for']}, labels=rule['labels'], annotations=rule['annotations']))
        (path/'alert-rules.yml').write_text(yaml.safe_dump({'groups': [{'name': 'alerts', 'rules': derived}]}))
        scenarios = yaml.safe_load((ROOT/'tests/alert-scenarios.yml').read_text())
        for i, scenario in enumerate(scenarios['tests']):
            scenario['alert_rule_test'] = []
            for rule in rules:
                uid = rule['uid']
                labels = dict(rule['labels'])
                if uid in ('docker-app-down', 'docker-exporter-down'):
                    job = 'service-a' if uid=='docker-app-down' else 'cadvisor'
                    labels.update(job=job, instance=job+(':8000' if job=='service-a' else ':8080'))
                elif uid in ('docker-http-errors', 'docker-high-latency'):
                    labels.update(job='service-a')
                else:
                    labels.update(instance='host')
                    if uid != 'docker-high-cpu':
                        labels.update(job='node-exporter')
                    if uid == 'docker-disk-full':
                        labels.update(device='/dev/sda', mountpoint='/', fstype='ext4')
                scenario['alert_rule_test'].append(dict(eval_time='15m', alertname=uid,
                    exp_alerts=[dict(exp_labels=labels, exp_annotations=rule['annotations'])] if i==0 else []))
        (path/'scenarios.yml').write_text(yaml.safe_dump(scenarios))
        run('docker', 'run', '--rm', '--entrypoint', '/bin/promtool', '-v',
            f'{tmp}:/validation:ro', '-w', '/validation', 'prom/prometheus:latest',
            'test', 'rules', '/validation/scenarios.yml')
    print('Configuration and all dashboard/alert PromQL expressions validated.')

if __name__ == '__main__':
    main()
