#!/usr/bin/env python3
"""Isolated smoke test. Requires cached/built reverse-proxy images and Docker.
Only resources with a fresh UUID prefix are created and cleaned up.
Existing containers, networks and volumes are never changed.
"""
import base64
import json
import math
import os
from pathlib import Path
import secrets
import subprocess
import time
import urllib.request
import urllib.parse
import uuid

ROOT = Path(__file__).resolve().parents[1]

def docker(*args):
    return subprocess.check_output(['docker', *args], text=True).strip()

def main():
    prefix = 'monitoring-test-' + uuid.uuid4().hex[:10]
    containers = []
    password = secrets.token_urlsafe(24)
    docker('network', 'create', prefix)
    def start(name, image, *args, command=()):
        full = prefix + '-' + name
        containers.append(full)
        docker('run', '-d', '--name', full, '--network', prefix,
               '--network-alias', name, *args, image, *command)
        return full
    def request(port, route, auth=False):
        req = urllib.request.Request(f'http://127.0.0.1:{port}{route}')
        if auth:
            token = base64.b64encode(f'admin:{password}'.encode()).decode()
            req.add_header('Authorization', 'Basic '+token)
        return json.load(urllib.request.urlopen(req, timeout=5))
    def port(name, internal):
        return docker('port', name, str(internal)).split(':')[-1]
    def wait(check, label, attempts=90):
        last = None
        for _ in range(attempts):
            try:
                result = check()
                if result:
                    print(label + ': OK', flush=True)
                    return result
            except Exception as exc:
                last = exc
            time.sleep(2)
        raise RuntimeError(f'{label} timed out: {last}')
    try:
        for name in ('service-a', 'service-b'):
            start(name, f'reverse-proxy-project-{name}:latest')
        nginx = start('nginx', 'nginx:latest', '-p', '127.0.0.1::80',
                      '-v', f'{ROOT.parent}/reverse-proxy-project/nginx/nginx.conf:/etc/nginx/nginx.conf:ro')
        start('node-exporter', 'prom/node-exporter:latest', '--pid', 'host',
              '-v', '/:/host:ro', command=('--path.rootfs=/host',))
        start('cadvisor', 'ghcr.io/google/cadvisor:0.55.1', '--privileged', '--pid', 'host',
              '-v', '/:/rootfs:ro', '-v', '/var/run:/var/run:ro',
              '-v', '/sys:/sys:ro', '-v', '/var/lib/docker:/var/lib/docker:ro',
              '-v', '/dev/disk:/dev/disk:ro', '--device', '/dev/kmsg',
              command=('--containerd='+os.environ.get('CADVISOR_CONTAINERD_SOCKET',
                      '/proc/1/root/run/containerd/containerd.sock'),))
        prom = start('prometheus', 'prom/prometheus:latest', '-p', '127.0.0.1::9090',
                     '-v', f'{ROOT}/prometheus:/etc/prometheus:ro', '--tmpfs', '/prometheus:uid=65534,gid=65534')
        graf = start('grafana', 'grafana/grafana:12.1', '-p', '127.0.0.1::3000',
                     '-e', f'GF_SECURITY_ADMIN_PASSWORD={password}', '-e', 'GF_SMTP_ENABLED=false',
                     '-v', f'{ROOT}/grafana/provisioning:/etc/grafana/provisioning:ro',
                     '-v', f'{ROOT}/grafana/dashboards:/var/lib/grafana/dashboards:ro',
                     '--tmpfs', '/var/lib/grafana:uid=472,gid=0')
        pp, gp = port(prom, 9090), port(graf, 3000)
        np = port(nginx, 80)
        for endpoint in ('users', 'cv'):
            wait(lambda: request(np, '/'+endpoint).get('message'), 'Nginx /'+endpoint)
        wait(lambda: request(gp, '/api/health')['database']=='ok', 'Grafana startup')
        targets = wait(lambda: (lambda ts: ts if len(ts)==5 and all(t['health']=='up' for t in ts) else None)(request(pp, '/api/v1/targets')['data']['activeTargets']), 'All five Prometheus targets')
        for name, endpoint in [('service-a', 'users'), ('service-b', 'cv')]:
            docker('exec', prefix+'-'+name, 'python', '-c',
                   f'import urllib.request; [urllib.request.urlopen("http://localhost:8000/{endpoint}").read() for _ in range(10)]')
        wait(lambda: len(request(gp, '/api/search?tag=monitoring', True))==2, 'Both provisioned dashboards')
        rules = request(gp, '/api/v1/provisioning/alert-rules', True)
        assert len(rules)==7, rules
        print('Seven Grafana alert rules imported: OK', flush=True)
        # Allow two scrapes for application rate/histogram series.
        wait(lambda: len(request(pp, '/api/v1/query?query=requests_total')['data']['result'])==2, 'Both FastAPI request counters')
        wait(lambda: len(request(pp, '/api/v1/query?query=http_request_duration_seconds_count')['data']['result'])==2, 'Both FastAPI latency histograms')
        # Verify the actual filtered panel queries, not only raw exporter metrics.
        for path in (ROOT/'grafana/dashboards').glob('*.json'):
            for panel in json.loads(path.read_text())['panels']:
                if panel['title'] == 'HTTP errors':
                    continue  # Error-label series do not exist before first error.
                for target in panel['targets']:
                    query = urllib.parse.urlencode({'query': target['expr']})
                    def finite_series():
                        rows = request(pp, '/api/v1/query?'+query)['data']['result']
                        return rows and all(math.isfinite(float(row['value'][1])) for row in rows)
                    wait(finite_series, 'Panel '+panel['title'])
        docker('stop', prefix+'-service-a')
        wait(lambda: any(t['labels']['job']=='service-a' and t['health']=='down' for t in request(pp, '/api/v1/targets')['data']['activeTargets']), 'Application failure detected')
        # Alert pending lasts two minutes plus up to one evaluation interval.
        def firing():
            groups = request(gp, '/api/prometheus/grafana/api/v1/rules', True)['data']['groups']
            return any(r.get('state')=='firing' and r.get('name')=='Application metrics unavailable'
                       for group in groups for r in group['rules'])
        wait(firing, 'Application-down Grafana alert firing', attempts=120)
        docker('start', prefix+'-service-a')
        wait(lambda: all(t['health']=='up' for t in request(pp, '/api/v1/targets')['data']['activeTargets']), 'Application scrape recovered')
        wait(lambda: not firing(), 'Application-down Grafana alert recovered')
    except Exception:
        for name in containers:
            print(docker('logs', '--tail', '15', name))
        raise
    finally:
        for name in reversed(containers):
            subprocess.run(['docker', 'rm', '-f', name], check=False, stdout=subprocess.DEVNULL)
        docker('network', 'rm', prefix)

if __name__ == '__main__':
    main()
