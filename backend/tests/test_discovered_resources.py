"""Discovery persists manual resources and makes existing action endpoints usable."""
import json
import shlex
from uuid import uuid4

from sqlalchemy import select

from conftest import linked
from dingofs_platform.clusters.transport import ClusterCommandResult, ExecutionIdentity
from dingofs_platform.resources.models import ManagedResource


def execute(admin, c, action, parameters=None):
    response = admin.post(f'/api/v1/clusters/{c["id"]}/resource-operations', json=dict(
        action=action, parameters=parameters or {}, confirmed=True,
        request_id=str(uuid4()), base_revision=c["revision"]))
    assert response.status_code == 202, response.text
    op = admin.get('/api/v1/resource-operations/' + response.json()['id']).json()
    assert op['state'] == 'succeeded', op
    return op


def test_scan_upserts_external_mount_and_unmount_uses_external_lifecycle(admin, app):
    m, c, _ = linked(admin)
    rid = str(uuid4())
    requests = []
    row = dict(mount_id='42', mount_path='/mnt/manual', fs_name='manual', pid=123,
        client_user='jenkins', cluster_match='current', mds_addresses=['a:6900'],
        adopted_resource_id=rid, identity=dict(pid=123, start_ticks='17', exe='/opt/dingo-client',
                                             mount_id='42', namespace='mnt:[1]'))
    def transport(config, cmd, **kw):
        req = json.loads(shlex.split(cmd.resource_script)[-1])
        requests.append(req)
        assert cmd.target_user == 'root' and not cmd.resource_requires_dingo
        data = {'mounts': [row, {**row, 'mount_path': '/mnt/foreign', 'cluster_match': 'other'}]} if req['action'] == 'mount.scan' else {}
        return ClusterCommandResult(ExecutionIdentity('root', '/root', ''), json.dumps(dict(
            state='unmounted' if req['action'] == 'mount.unmount' else 'succeeded', data=data, returncode=0)), '', 0)
    app.state.resource_transport = transport
    for _ in range(2):
        op = execute(admin, c, 'mount.scan', {'machine_ids': [m['id']]})
        assert op['result']['steps'][0]['data']['mounts'][0]['saved_resource_id'] == rid
    snapshot = admin.get(f'/api/v1/clusters/{c["id"]}/resources').json()
    mounts = [r for r in snapshot['resources'] if r['kind'] == 'mount']
    assert len(mounts) == 1 and mounts[0]['state'] == 'mounted'
    assert mounts[0]['data']['client_user'] == 'jenkins'
    execute(admin, c, 'mount.unmount', {'resource_id': rid})
    assert requests[-1]['record']['origin'] == 'external'
    with app.state.session_factory() as db:
        assert db.get(ManagedResource, rid).state == 'unmounted'


def test_filesystem_and_cache_queries_persist_manual_resources_and_delete_syncs(admin, app):
    _, c, _ = linked(admin)
    member_id = str(uuid4())
    def transport(config, cmd, **kw):
        req = json.loads(shlex.split(cmd.resource_script)[-1])
        if req['action'] == 'fs.list':
            data = {'result': {'fs_infos': [{'fs_name': 'manual', 'fs_id': 17, 'secret_key': 'never-store'}]}}
        elif req['action'] == 'cache.list':
            data = {'groups': {'result': {'group_names': ['external-group']}},
                    'members': {'result': {'members': [dict(member_id=member_id, group_name='external-group',
                                                           ip='192.0.2.1', port=21000, state=1)]}}}
        else:
            data = {}
        return ClusterCommandResult(ExecutionIdentity('test', '/home/test', '/opt/dingo'),
            json.dumps(dict(state='succeeded', data=data, returncode=0)), '', 0)
    app.state.resource_transport = transport
    for _ in range(2):
        execute(admin, c, 'fs.list')
        execute(admin, c, 'cache.list')
    with app.state.session_factory() as db:
        rows = list(db.scalars(select(ManagedResource)))
        assert len(rows) == 2
        fs = next(r for r in rows if r.kind == 'filesystem')
        cache = next(r for r in rows if r.kind == 'cache')
        assert 'never-store' not in json.dumps(fs.data)
        assert cache.data['members'][0]['origin'] == 'external'
    execute(admin, c, 'fs.delete', {'fs_name': 'manual'})
    execute(admin, c, 'cache.delete', {'member_id': member_id})
    with app.state.session_factory() as db:
        assert all(r.state == 'deleted' for r in db.scalars(select(ManagedResource)))


def test_saved_external_cache_still_requires_machine_resolution(admin, app):
    _, c, _ = linked(admin)
    rid = str(uuid4())
    with app.state.session_factory.begin() as db:
        from dingofs_platform.inventory.models import Cluster
        cluster = db.get(Cluster, c['id'])
        db.add(ManagedResource(id=rid, cluster_id=c['id'], creator_id=cluster.creator_id,
            kind='cache', name='external', state='running', data=dict(origin='external',
                members=[dict(member_id=str(uuid4()), origin='external')])))
    app.state.resource_transport = lambda *a, **k: (_ for _ in ()).throw(AssertionError('must not SSH'))
    response = admin.post(f'/api/v1/clusters/{c["id"]}/resource-operations', json=dict(
        action='cache.stop', parameters={'resource_id': rid}, confirmed=True,
        request_id=str(uuid4()), base_revision=c['revision']))
    assert response.status_code == 422
    assert response.json()['code'] == 'cache_list_required'


def test_refresh_reconciles_manually_removed_filesystem(admin, app):
    _, c, _ = linked(admin)
    rows = [{'fs_name': 'manual', 'fs_id': 7}]
    def transport(config, cmd, **kw):
        return ClusterCommandResult(ExecutionIdentity('test', '/home/test', '/opt/dingo'),
            json.dumps(dict(state='succeeded', returncode=0, data={'result': {'fs_infos': rows}})), '', 0)
    app.state.resource_transport = transport
    execute(admin, c, 'fs.list')
    rows.clear()
    execute(admin, c, 'fs.list')
    with app.state.session_factory() as db:
        assert db.scalar(select(ManagedResource)).state == 'deleted'
