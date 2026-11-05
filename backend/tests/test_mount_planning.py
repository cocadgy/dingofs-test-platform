from uuid import uuid4
import pytest
from dingofs_platform.resources.schemas import validate


def client(**extra):
    return dict(machine_id=str(uuid4()), target_user='test', mount_path='/mnt/train', **extra)


def test_mount_plan_validates_and_expands_clients():
    from dingofs_platform.resources.mount_planning import expand_clients
    first, second = client(count=2), client(count=2)
    result = validate('mount.plan', dict(fs_name='train', clients=[first, second]))
    rows = expand_clients(result)
    assert len(rows) == 4
    assert [r['mount_path'] for r in rows] == ['/mnt/train-001', '/mnt/train-002'] * 2
    assert all(r['fs_name'] == 'train' and r['count'] == 1 for r in rows)


def test_mount_plan_rejects_duplicate_paths_and_excessive_counts():
    from dingofs_platform.resources.mount_planning import expand_clients
    row = client()
    with pytest.raises(ValueError, match='重复'):
        expand_clients(validate('mount.plan', dict(fs_name='train', clients=[row, row])))
    with pytest.raises(ValueError):
        validate('mount.plan', dict(fs_name='train', clients=[client(count=1001)]))


def test_mount_plan_pins_binary_and_rejects_unknown_parameters():
    row = client(binary_source='tag', binary_tag='v5.2', binary_digest='sha256:' + 'a' * 64)
    assert validate('mount.plan', dict(fs_name='train', clients=[row]))['clients'][0]['binary_digest'] == row['binary_digest']
    with pytest.raises(ValueError):
        validate('mount.plan', dict(fs_name='train', clients=[{**row, 'binary_digest': 'latest'}]))
    with pytest.raises(ValueError):
        validate('mount.create', dict(plan_id=str(uuid4()), mount_path='/mnt/other'))


def test_mount_plan_isolated_cache_directories():
    from dingofs_platform.resources.mount_planning import expand_clients
    row = client(count=2, mount_options={'cache_dir': '/mnt/cache'})
    rows = expand_clients(validate('mount.plan', dict(fs_name='train', clients=[row])))
    assert [r['mount_options']['cache_dir'] for r in rows] == ['/mnt/cache-001', '/mnt/cache-002']


from conftest import linked
from test_resource_api import runner, begin
from dingofs_platform.clusters.transport import ClusterCommandResult, ExecutionIdentity
import json


def test_mount_plan_execute_and_partial_retry(admin, app, runner):
    machine, cluster, _ = linked(admin)
    calls = []
    fail_second = [True]
    def transport(config, cmd, **kw):
        work = json.loads(cmd.resource_script)
        calls.append(work)
        planning = work['action'] == 'mount.plan'
        failure = not planning and work['record']['mount_path'].endswith('002') and fail_second[0]
        data = {'effective_port': 10000 + len(calls), 'binary_info': {'path': '/opt/dingo-client', 'sha256': 'a' * 64, 'version': 'v5.2'}} if planning else {}
        return ClusterCommandResult(ExecutionIdentity('test', '/home/test', '/bin/dingo'), json.dumps({
            'state': 'failed' if failure else 'planned' if planning else 'mounted', 'returncode': int(failure), 'data': data,
        }), '', int(failure))
    app.state.resource_transport = transport
    payload = dict(fs_name='train', clients=[dict(machine_id=machine['id'], target_user='test', mount_path='/mnt/train', count=3)])
    response = begin(admin, cluster, 'mount.plan', payload)
    assert response.status_code == 202, response.text
    plan = admin.get('/api/v1/resource-operations/' + response.json()['id']).json()
    assert plan['state'] == 'succeeded', plan
    response = begin(admin, cluster, 'mount.create', {'plan_id': plan['id']})
    assert response.status_code == 202, response.text
    op = admin.get('/api/v1/resource-operations/' + response.json()['id']).json()
    assert op['state'] == 'failed', op
    assert begin(admin, cluster, 'mount.create', {'plan_id': plan['id']}).status_code == 409
    fail_second[0] = False
    response = begin(admin, cluster, 'mount.create', {'retry_operation_id': op['id']})
    assert response.status_code == 202, response.text
    retried = admin.get('/api/v1/resource-operations/' + response.json()['id']).json()
    assert retried['state'] == 'succeeded', retried
    mounts = [work for work in calls if work['action'] == 'mount.create']
    assert [work['record']['mount_path'] for work in mounts] == ['/mnt/train-001', '/mnt/train-002', '/mnt/train-002', '/mnt/train-003']
