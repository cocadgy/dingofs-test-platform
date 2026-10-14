from conftest import linked
from dingofs_platform.dashboard.monitor import cluster_probe, machine_probe
from dingofs_platform.inventory.ssh_transport import CollectionError


def test_dashboard_lists_machine_and_cluster_without_exposing_credentials(admin):
    machine, cluster, _ = linked(admin)
    response = admin.get('/api/v1/dashboard')
    assert response.status_code == 200, response.text
    data = response.json()
    m = next(item for item in data['machines'] if item['id'] == machine['id'])
    c = next(item for item in data['clusters'] if item['id'] == cluster['id'])
    assert m['probe'] is None
    assert m['name'] == machine['name']
    assert c['name'] == cluster['name']
    assert 'ssh_password' not in str(data)
    assert 'credential_ref' not in str(data)
    assert data['progress']['running'] is False


def test_machine_probe_distinguishes_authentication_failure_from_success(monkeypatch):
    from types import SimpleNamespace
    machine = SimpleNamespace(address='localhost', ssh_port=22, ssh_user='test',
                              ssh_password_ciphertext='encrypted')
    settings = SimpleNamespace(credential_encryption_key='key')
    monkeypatch.setattr('dingofs_platform.dashboard.monitor.decrypt_password', lambda *args: 'secret')
    def denied(*args, **kwargs):
        raise CollectionError('authentication_failed')
    monkeypatch.setattr('dingofs_platform.dashboard.monitor.execute_ssh', denied)
    assert machine_probe(machine, settings)['error'] == 'authentication_failed'
    monkeypatch.setattr('dingofs_platform.dashboard.monitor.execute_ssh',
                        lambda *args, **kwargs: {'probe': SimpleNamespace(returncode=0, stdout='{}')})
    assert machine_probe(machine, settings)['state'] == 'healthy'


def test_cluster_probe_reports_real_service_state(monkeypatch):
    from pathlib import Path
    from types import SimpleNamespace
    from dingofs_platform.clusters.transport import ClusterCommandResult, ExecutionIdentity
    raw = (Path(__file__).parent / 'fixtures/dingo/cluster-status-main.txt').read_text()
    cluster = SimpleNamespace(binding_state='verified', os_user='root',
                              external_name='main-dingofs', execution_home='/root')
    machine = SimpleNamespace(address='localhost', ssh_port=22, ssh_user='test',
                              ssh_password_ciphertext='encrypted')
    settings = SimpleNamespace(credential_encryption_key='key', cluster_status_timeout=30,
                               cluster_max_bytes=2097152)
    monkeypatch.setattr('dingofs_platform.dashboard.monitor.decrypt_password', lambda *args: 'secret')
    monkeypatch.setattr('dingofs_platform.dashboard.monitor.execute_cluster',
                        lambda *args, **kwargs: ClusterCommandResult(
                            ExecutionIdentity('root', '/root', '/bin/dingo'), raw, '', 0))
    result = cluster_probe(cluster, machine, settings)
    assert result['state'] == 'running'
    assert result['snapshot']['running_instances'] == result['snapshot']['expected_instances']


def test_fresh_cluster_probe_overrides_earlier_failed_collection(admin):
    from types import SimpleNamespace
    from dingofs_platform.inventory.models import Cluster
    _, cluster, _ = linked(admin)
    with admin.app.state.session_factory.begin() as db:
        row = db.get(Cluster, cluster['id'])
        row.status_attempt_state = 'failed'
        row.status_error_code = 'invalid_header'
    admin.app.state.dashboard_monitor = SimpleNamespace(snapshot=lambda: ({}, {
        cluster['id']: {'state': 'running', 'error': None,
                        'checked_at': '2026-10-12T10:00:00+00:00',
                        'snapshot': {'state': 'running', 'service_count': 1,
                                     'running_instances': 1, 'expected_instances': 1,
                                     'services': [{'id': 's1', 'role': 'mds', 'state': 'running',
                                                   'running_instances': 1, 'expected_instances': 1}]}}
    }, {'running': False, 'completed': 1, 'total': 1}))
    response = admin.get('/api/v1/dashboard')
    assert response.status_code == 200, response.text
    current = next(item for item in response.json()['clusters'] if item['id'] == cluster['id'])
    assert current['state'] == 'running'
    assert current['last_error'] is None
    assert current['roles']['mds'] == {'running': 1, 'expected': 1}


def test_machine_probe_returns_usage_and_preserves_connection_when_metrics_fail(monkeypatch):
    import json
    from types import SimpleNamespace
    machine = SimpleNamespace(address='localhost', ssh_port=22, ssh_user='test',
                              ssh_password_ciphertext='encrypted')
    settings = SimpleNamespace(credential_encryption_key='key')
    monkeypatch.setattr('dingofs_platform.dashboard.monitor.decrypt_password', lambda *args: 'secret')
    metrics = {'cpu_percent': 25.0, 'memory_used_bytes': 300, 'memory_total_bytes': 1000,
               'disks': [{'mountpoint': '/mnt/disk1', 'device': '/dev/nvme0n1',
                          'used_bytes': 910, 'total_bytes': 1000, 'percent': 91.0}]}
    monkeypatch.setattr('dingofs_platform.dashboard.monitor.execute_ssh',
                        lambda *args, **kwargs: {'probe': SimpleNamespace(returncode=0,
                                                     stdout=json.dumps(metrics))})
    result = machine_probe(machine, settings)
    assert result['state'] == 'healthy'
    assert result['usage'] == metrics
    monkeypatch.setattr('dingofs_platform.dashboard.monitor.execute_ssh',
                        lambda *args, **kwargs: {'probe': SimpleNamespace(returncode=0, stdout='bad')})
    result = machine_probe(machine, settings)
    assert result['state'] == 'healthy'
    assert result['usage'] is None
    assert result['usage_error'] == 'invalid_metrics'


def test_resource_sampler_reports_local_usage_with_bounded_output():
    import subprocess
    from dingofs_platform.dashboard.usage import SAMPLE_COMMAND, parse_usage
    result = subprocess.run(SAMPLE_COMMAND, shell=True, capture_output=True, text=True, timeout=5)
    assert result.returncode == 0, result.stderr
    usage = parse_usage(result.stdout)
    assert 0 <= usage['cpu_percent'] <= 100
    assert 0 <= usage['memory_used_bytes'] <= usage['memory_total_bytes']
    assert all(disk['total_bytes'] > 0 for disk in usage['disks'])


def test_sampler_merges_duplicate_local_mounts_and_skips_virtual_mounts():
    import json
    import subprocess
    import sys
    from dingofs_platform.dashboard.usage import SAMPLE_SCRIPT
    setup = '''import builtins, io, os
from types import SimpleNamespace
original = builtins.open
def fake_open(path, *args, **kwargs):
    if path == '/proc/stat':
        return io.StringIO('cpu  1 2 3 4 5 6 7 8 9 10\\n')
    if path == '/proc/meminfo':
        return io.StringIO('MemTotal: 1000 kB\\nMemAvailable: 200 kB\\n')
    if path == '/proc/self/mountinfo':
        return io.StringIO('1 0 8:1 / / rw - xfs /dev/sda1 rw\\n'
                           '2 0 8:1 /data /mnt/data rw - xfs /dev/sda1 rw\\n'
                           '3 0 0:42 / /run rw - tmpfs tmpfs rw\\n')
    return original(path, *args, **kwargs)
builtins.open = fake_open
os.statvfs = lambda path: SimpleNamespace(f_blocks=1000, f_bfree=100, f_frsize=1)
'''
    process = subprocess.run([sys.executable, '-c', setup + SAMPLE_SCRIPT],
                             capture_output=True, text=True, timeout=5)
    assert process.returncode == 0, process.stderr
    disks = json.loads(process.stdout)['disks']
    assert disks == [{'mountpoint': '/', 'mountpoints': ['/', '/mnt/data'],
                      'device': '/dev/sda1', 'used_bytes': 900,
                      'total_bytes': 1000, 'percent': 90.0}]
