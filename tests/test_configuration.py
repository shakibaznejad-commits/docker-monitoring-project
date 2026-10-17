import json
from pathlib import Path
import subprocess
import unittest
import yaml

ROOT = Path(__file__).resolve().parents[1]

class ConfigurationTests(unittest.TestCase):
    def test_dashboards_cover_required_metrics(self):
        expressions = []
        for name in ('infrastructure', 'application'):
            dashboard = json.loads((ROOT / f'grafana/dashboards/{name}.json').read_text())
            self.assertTrue(dashboard['panels'])
            for panel in dashboard['panels']:
                self.assertEqual(panel['datasource']['uid'], 'monitoring-prometheus')
                expressions.extend(t['expr'] for t in panel['targets'])
        joined = ' '.join(expressions)
        for metric in ('node_cpu_seconds_total', 'node_memory_MemAvailable_bytes',
                       'node_filesystem_avail_bytes', 'container_memory_working_set_bytes',
                       'requests_total', 'http_responses_total', 'http_request_duration_seconds_bucket'):
            self.assertIn(metric, joined)

    def test_service_discovery(self):
        cfg = yaml.safe_load((ROOT / 'prometheus/prometheus.yml').read_text())
        jobs = {j['job_name']: j for j in cfg['scrape_configs']}
        for name in ('service-a', 'service-b'):
            self.assertEqual(jobs[name]['static_configs'][0]['targets'], [f'{name}:8000'])

    def test_alerts_have_delays_and_explicit_failure_states(self):
        cfg = yaml.safe_load((ROOT / 'grafana/provisioning/alerting/alerts.yml').read_text())
        rules = cfg['groups'][0]['rules']
        self.assertGreaterEqual(len(rules), 6)
        for rule in rules:
            self.assertNotEqual(rule['for'], '0s')
            self.assertEqual(rule['execErrState'], 'Error')
            self.assertIn(rule['labels']['severity'], ('warning', 'critical'))
            self.assertEqual(rule['data'][0]['datasourceUid'], 'monitoring-prometheus')

    def test_secrets_are_ignored(self):
        for name in ('.env', '.env.local'):
            self.assertEqual(subprocess.run(['git', 'check-ignore', '-q', name], cwd=ROOT).returncode, 0)
        tracked = subprocess.check_output(['git', 'ls-files'], cwd=ROOT, text=True).splitlines()
        self.assertFalse(any(p == '.env' or (p.startswith('.env.') and p != '.env.example') for p in tracked))

if __name__ == '__main__':
    unittest.main()
