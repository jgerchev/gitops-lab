#!/usr/bin/env python3
"""Offline checks only: never contact SSH, libvirt, Docker, or Kubernetes.

Requires PyYAML. Optional artifact paths also exercise the transport with fake
curl/SSH: real release bytes are verified, but no remote command is executed.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest

import yaml

ROOT = Path(__file__).resolve().parent
PARSER = argparse.ArgumentParser(description=__doc__)
PARSER.add_argument('--argocd-manifest', type=Path)
PARSER.add_argument('--k3s-binary', type=Path)
ARGS = PARSER.parse_args()


def run(*args, **kwargs):
    return subprocess.run(args, cwd=ROOT.parent, text=True, capture_output=True,
                          timeout=60, **kwargs)


def load(name):
    return yaml.safe_load((ROOT / name).read_text())


def pins():
    return dict(re.findall(r"^([A-Z0-9_]+)='([^']+)'$",
                           (ROOT / 'versions.env').read_text(), re.M))


class StaticTests(unittest.TestCase):
    def embedded_python(self):
        blocks = re.findall(r"python3 [^\n]+ <<'PY'\n(.*?)\nPY", (ROOT / 'guest.sh').read_text(), re.S)
        self.assertEqual(len(blocks), 2)
        for block in blocks:
            compile(block, '<guest embedded Python>', 'exec')
        return blocks

    def test_runtime_version_drift_guards_with_local_fixtures(self):
        code = self.embedded_python()[0]
        with tempfile.TemporaryDirectory(prefix='gitops-lab-guard-') as t:
            path = Path(t) / 'workloads.json'
            for image, host_network, host_port, expected in [
                ('quay.io/argoproj/argocd:v3.6.1', False, 0, 0),
                ('quay.io/argoproj/argocd:v3.6.0', False, 0, 1),
                ('other.example/argocd:v3.6.1', False, 0, 1),
                ('quay.io/argoproj/argocd:v3.6.1', True, 0, 1),
                ('quay.io/argoproj/argocd:v3.6.1', False, 8080, 1),
            ]:
                path.write_text(json.dumps({'items': [{
                    'metadata': {'name': 'argocd-server'},
                    'spec': {'template': {'spec': {'hostNetwork': host_network, 'containers': [{
                        'name': 'argocd-server', 'image': image, 'ports': [{'hostPort': host_port}]
                    }]}}}
                }]}))
                p = run('python3', '-c', code, str(path), 'v3.6.1')
                self.assertEqual(p.returncode, expected, p.stderr)

    def test_runtime_exposure_guards_with_local_fixtures(self):
        code = self.embedded_python()[1]
        with tempfile.TemporaryDirectory(prefix='gitops-lab-exposure-') as t:
            path = Path(t) / 'services.json'
            for kind, spec, expected in [
                ('Service', {'type': 'ClusterIP'}, 0),
                ('Service', {'type': 'NodePort'}, 1),
                ('Service', {'type': 'LoadBalancer'}, 1),
                ('Service', {'type': 'ClusterIP', 'externalIPs': ['192.0.2.1']}, 1),
                ('Ingress', {}, 1),
            ]:
                path.write_text(json.dumps({'items': [{'kind': kind, 'spec': spec}]}))
                p = run('python3', '-c', code, str(path))
                self.assertEqual(p.returncode, expected, p.stderr)

    def test_shell_syntax(self):
        for name in ('bootstrap.sh', 'guest.sh', 'versions.env'):
            p = run('bash', '-n', str(ROOT / name))
            self.assertEqual(p.returncode, 0, p.stderr)

    def test_help_and_invalid_arguments_are_offline(self):
        for args, expected in [(('--help',), 0), ((), 1),
                               (('--target', 'root@host'), 1),
                               (('--target', 'lab@host;id'), 1),
                               (('--identity',), 1), (('--bogus',), 1)]:
            p = run('bash', str(ROOT / 'bootstrap.sh'), *args)
            self.assertEqual(p.returncode, expected, p.stderr)
            self.assertNotIn('Downloading', p.stdout)

    def test_render(self):
        p = run('bash', str(ROOT / 'bootstrap.sh'), '--render')
        self.assertEqual(p.returncode, 0, p.stderr)
        docs = list(yaml.safe_load_all(p.stdout))
        self.assertEqual([d['kind'] for d in docs],
                         ['Namespace', 'AppProject', 'Application'])
        self.assertEqual({d['metadata']['name'] for d in docs}, {'argocd', 'gitops-lab'})

    def test_versions(self):
        p = pins()
        self.assertEqual(p['K3S_VERSION'], 'v1.37.2+k3s1')
        self.assertEqual(p['ARGO_VERSION'], 'v3.6.1')
        for component in ('K3S', 'ARGO'):
            self.assertRegex(p[component + '_SHA256'], r'^[a-f0-9]{64}$')
            self.assertTrue(p[component + '_URL'].startswith('https://'))
        self.assertNotIn('get.k3s.io', p['K3S_URL'])

    def test_application_interface(self):
        d = load('application.yaml')
        self.assertEqual(d['metadata'], {'name': 'gitops-lab', 'namespace': 'argocd'})
        spec = d['spec']
        self.assertEqual(spec['project'], 'gitops-lab')
        self.assertEqual(spec['source'], {'repoURL': 'https://github.com/jgerchev/gitops-lab',
                                         'targetRevision': 'main', 'path': 'gitops'})
        self.assertEqual(spec['destination'], {'server': 'https://kubernetes.default.svc',
                                              'namespace': 'gitops-lab'})
        self.assertEqual(spec['syncPolicy']['automated'],
                         {'prune': True, 'selfHeal': True, 'allowEmpty': False})
        self.assertNotIn('CreateNamespace=true', spec['syncPolicy']['syncOptions'])

    def test_project_only_allows_namespace_cluster_permission(self):
        s = load('project.yaml')['spec']
        self.assertEqual(s['clusterResourceWhitelist'], [{'group': '', 'kind': 'Namespace'}])
        self.assertEqual(s['sourceRepos'], ['https://github.com/jgerchev/gitops-lab'])
        self.assertEqual(s['sourceNamespaces'], ['argocd'])
        self.assertEqual(s['destinations'], [{'namespace': 'gitops-lab',
                                             'server': 'https://kubernetes.default.svc'}])
        self.assertEqual({(x['group'], x['kind']) for x in s['namespaceResourceWhitelist']},
                         {('apps', 'Deployment'), ('', 'Service'),
                          ('networking.k8s.io', 'Ingress')})

    def test_k3s_pod_reachable_api_protected_config_default_traefik(self):
        c = load('k3s-config.yaml')
        self.assertEqual(c['bind-address'], '0.0.0.0')
        self.assertEqual(c['write-kubeconfig-mode'], '0600')
        self.assertEqual(c['cluster-cidr'], '10.42.0.0/16')
        self.assertEqual(c['service-cidr'], '10.43.0.0/16')
        self.assertNotIn('disable', c)
        self.assertNotIn('disable-agent', c)

    def test_safe_apply_and_guards_present(self):
        g = (ROOT / 'guest.sh').read_text()
        # Strip comments so documentation of forbidden flags doesn't trigger.
        commands = '\n'.join(line for line in g.splitlines() if not line.lstrip().startswith('#'))
        self.assertNotIn('--force-conflicts', commands)
        self.assertIn('--server-side', commands)
        self.assertIn('condition=Established', commands)
        self.assertIn('flock -w 10', commands)
        self.assertIn('configuration drift:', commands)
        self.assertIn('installed K3s bytes differ', commands)
        self.assertIn('argocd-owned', commands)
        self.assertIn('ClusterIP', commands)
        self.assertNotIn('set -x', commands)
        self.assertNotIn('apt-get', commands)


@unittest.skipUnless(ARGS.argocd_manifest and ARGS.k3s_binary, 'optional release artifacts not supplied')
class ArtifactTests(unittest.TestCase):
    def test_release_bytes_match_pins(self):
        for name, path in [('ARGO', ARGS.argocd_manifest), ('K3S', ARGS.k3s_binary)]:
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), pins()[name + '_SHA256'])

    def test_non_ha_manifest_crds_and_unexposed_service(self):
        docs = list(yaml.safe_load_all(ARGS.argocd_manifest.read_text()))
        crds = [d for d in docs if d['kind'] == 'CustomResourceDefinition']
        self.assertEqual(len(crds), 3)
        # Confirms why ordinary client-side apply is unsuitable.
        self.assertTrue(any(len(yaml.safe_dump(d)) > 262144 for d in crds))
        workloads = [d for d in docs if d['kind'] in ('Deployment', 'StatefulSet')]
        self.assertEqual(len(workloads), 7)
        for d in workloads:
            self.assertEqual(d['spec'].get('replicas', 1), 1)
            self.assertFalse(d['spec']['template']['spec'].get('hostNetwork', False))
        server = next(d for d in docs if d['kind'] == 'Service' and d['metadata']['name'] == 'argocd-server')
        self.assertEqual(server['spec'].get('type', 'ClusterIP'), 'ClusterIP')
        self.assertNotIn('externalIPs', server['spec'])
        self.assertFalse(any(d['kind'] == 'Ingress' for d in docs))
        for d in workloads:
            pod = d['spec']['template']['spec']
            for c in pod.get('containers', []) + pod.get('initContainers', []):
                if 'argoproj/argocd' in c['image']:
                    self.assertEqual(c['image'], 'quay.io/argoproj/argocd:v3.6.1')

    def test_transport_with_mock_curl_and_ssh_no_remote_execution(self):
        with tempfile.TemporaryDirectory(prefix='gitops-lab-test-') as t:
            t = Path(t)
            curl = t / 'curl'
            curl.write_text('''#!/usr/bin/env python3
import os, shutil, sys
url = next(a for a in sys.argv if a.startswith('https://'))
source = os.environ['TEST_K3S'] if url.endswith('/k3s') else os.environ['TEST_ARGO']
shutil.copyfile(source, sys.argv[sys.argv.index('-o') + 1])
''')
            ssh = t / 'ssh'
            ssh.write_text('''#!/usr/bin/env python3
import io, os, subprocess, sys, tarfile
assert 'lab@192.168.250.10' in sys.argv
assert 'StrictHostKeyChecking=yes' in sys.argv
assert 'BatchMode=yes' in sys.argv
assert 'user@jump.example' in sys.argv
p = subprocess.run(['bash', '-n'], input=sys.argv[-1], text=True, capture_output=True)
assert p.returncode == 0, p.stderr
with tarfile.open(fileobj=io.BytesIO(sys.stdin.buffer.read())) as archive:
    files = {m.name.removeprefix('./') for m in archive.getmembers() if m.isfile()}
    assert files == {'guest.sh', 'versions.env', 'k3s.service', 'k3s-config.yaml',
                     'namespaces.yaml', 'project.yaml', 'application.yaml', 'k3s', 'argocd-install.yaml'}
print('mock SSH: archive and remote shell syntax verified; NO remote execution')
''')
            curl.chmod(0o700)
            ssh.chmod(0o700)
            env = dict(os.environ, PATH=str(t) + os.pathsep + os.environ['PATH'],
                       TEST_K3S=str(ARGS.k3s_binary.resolve()),
                       TEST_ARGO=str(ARGS.argocd_manifest.resolve()), TMPDIR=str(t))
            p = run('bash', str(ROOT / 'bootstrap.sh'), '--target', 'lab@192.168.250.10',
                    '--jump', 'user@jump.example', env=env)
            self.assertEqual(p.returncode, 0, p.stderr)
            self.assertIn('NO remote execution', p.stdout)
            self.assertFalse(list(t.glob('gitops-lab-bootstrap.*')), 'temporary bundle not cleaned')


if __name__ == '__main__':
    unittest.main(argv=[sys.argv[0]], verbosity=2)
