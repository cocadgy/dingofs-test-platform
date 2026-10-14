from copy import deepcopy
import pytest
from dingofs_platform.resources import schemas


def test_mount_count_validated_and_single_compatible():
    p = dict(machine_id='node', target_user='test', fs_name='fs', mount_path='/mnt/test')
    assert schemas.validate('mount.create', p).get('count', 1) == 1
    assert schemas.validate('mount.create', {**p, 'count': 3})['count'] == 3
    for count in [0, -1, True, 1.5]:
        with pytest.raises(ValueError):
            schemas.validate('mount.create', {**p, 'count': count})


def test_cache_batch_expands_templates_without_shared_ids_or_ports():
    from dingofs_platform.resources.bulk_create import expand_cache_members
    template = dict(machine_id='node', target_user='test', cache_dir='/mnt/cache', port_mode='manual', listen_port=21000, member_id='')
    original = deepcopy(template)
    members = expand_cache_members([template], 3)
    assert len(members) == 3
    assert all(m['port_mode'] == 'auto' and not m.get('member_id') for m in members)
    members[0]['cache_dir'] = 'changed'
    assert members[1]['cache_dir'] == '/mnt/cache' and template == original
    with pytest.raises(ValueError):
        expand_cache_members([{**template, 'member_id': 'explicit'}], 2)
    assert len(expand_cache_members([template, template], 50)) == 100


def test_mount_batch_paths_are_unique_and_single_path_unchanged():
    from dingofs_platform.resources.bulk_create import mount_instances
    p = dict(mount_path='/mnt/test/', count=3, mount_options={'vfs_dummy_server_port':'10000'})
    children = mount_instances(p)
    assert [c['mount_path'] for c in children] == ['/mnt/test-001','/mnt/test-002','/mnt/test-003']
    assert all('count' not in c for c in children)
    assert mount_instances({'mount_path':'/mnt/test'}) == [{'mount_path':'/mnt/test'}]

from conftest import linked
from test_resource_api import runner, begin, member
from dingofs_platform.clusters.transport import ClusterCommandResult, ExecutionIdentity
import json
from uuid import uuid4


def resources(admin, cluster):
    return admin.get('/api/v1/clusters/'+cluster['id']+'/resources').json()['resources']


def test_batch_mount_records_and_replay(admin, app, runner):
    m,c,_ = linked(admin)
    calls=[]
    def transport(config, cmd, **kw):
        work=json.loads(cmd.resource_script); calls.append(work)
        return ClusterCommandResult(ExecutionIdentity('test','/home/test','/bin/dingo'), json.dumps({'state':'mounted','returncode':0,'data':{'vfs_dummy_server_port':10000+len(calls)}}), '', 0)
    app.state.resource_transport=transport
    params=dict(machine_id=m['id'],target_user='test',fs_name='fs',mount_path='/mnt/batch',count=3)
    rid=str(uuid4())
    response=begin(admin,c,'mount.create',params,rid)
    assert response.status_code==202,response.text
    op=admin.get('/api/v1/resource-operations/'+response.json()['id']).json()
    assert op['state']=='succeeded',op
    rows=sorted(resources(admin,c),key=lambda r:r['name'])
    assert [r['name'] for r in rows]==['/mnt/batch-001','/mnt/batch-002','/mnt/batch-003']
    assert all(r['state']=='mounted' for r in rows)
    assert [r['data']['vfs_dummy_server_port'] for r in rows]==[10001,10002,10003]
    assert len({r['data']['state_dir'] for r in rows})==3
    assert [s['mount_path'] for s in op['result']['steps']]==[r['name'] for r in rows]
    assert begin(admin,c,'mount.create',params,rid).json()['id']==op['id']
    assert len(calls)==3


def test_batch_mount_failure_preserves_success_and_marks_unattempted(admin, app, runner):
    m,c,_=linked(admin)
    calls=[]
    def transport(config,cmd,**kw):
        calls.append(cmd)
        failed=len(calls)==2
        return ClusterCommandResult(ExecutionIdentity('test','/home/test','/bin/dingo'),json.dumps({'state':'failed' if failed else 'mounted','returncode':int(failed),'message':'mount failed' if failed else '', 'data':{}}),'',int(failed))
    app.state.resource_transport=transport
    response=begin(admin,c,'mount.create',dict(machine_id=m['id'],target_user='test',fs_name='fs',mount_path='/mnt/batch',count=3))
    assert response.status_code==202,response.text
    op=admin.get('/api/v1/resource-operations/'+response.json()['id']).json()
    assert op['state']=='failed',op
    rows=sorted(resources(admin,c),key=lambda r:r['name'])
    assert [r['state'] for r in rows]==['mounted','unknown','not_started']
    assert len(calls)==2


def test_batch_cache_plan_and_create_unique_members(admin,app,runner):
    m,c,_=linked(admin)
    calls=[]
    def transport(config,cmd,**kw):
        work=json.loads(cmd.resource_script);calls.append(work)
        return ClusterCommandResult(ExecutionIdentity('test','/home/test','/bin/dingo'), json.dumps({'state':'succeeded','returncode':0,'data':{'effective_port':work['record']['listen_port']}}),'',0)
    app.state.resource_transport=transport
    response=begin(admin,c,'cache.plan',{'group_name':'batch','count':3,'members':[member(m['id'],21000)]})
    assert response.status_code==202,response.text
    plan=admin.get('/api/v1/resource-operations/'+response.json()['id']).json()
    assert plan['state']=='succeeded',plan
    response=begin(admin,c,'cache.create',{'plan_id':plan['id']})
    assert response.status_code==202,response.text
    op=admin.get('/api/v1/resource-operations/'+response.json()['id']).json()
    assert op['state']=='succeeded',op
    rows=resources(admin,c); assert len(rows)==1
    members=rows[0]['data']['members']
    assert len(members)==3
    for field in ['member_id','listen_port','cache_dir','log_dir']:
        assert len({m[field] for m in members})==3
    assert all(m['process_state']=='running' for m in members)
    assert len(calls)==6


def test_batch_conflict_reserves_nothing_and_starts_no_work(admin, runner):
    m,c,_=linked(admin)
    p=dict(machine_id=m['id'],target_user='test',fs_name='fs',mount_path='/mnt/atomic-002')
    assert begin(admin,c,'mount.create',p).status_code==202
    runner.clear()
    response=begin(admin,c,'mount.create',{**p,'mount_path':'/mnt/atomic','count':3})
    assert response.status_code==409,response.text
    assert len(resources(admin,c))==1
    assert runner==[]


def test_cancel_batch_while_auth_waiting_keeps_completed_mount(admin,app,runner):
    from dingofs_platform.clusters.transport import AuthenticationRequired
    m,c,_=linked(admin)
    calls=[]
    def transport(config,cmd,**kw):
        calls.append(cmd)
        if len(calls)==2: raise AuthenticationRequired('test')
        return ClusterCommandResult(ExecutionIdentity('test','/home/test','/bin/dingo'),'{"state":"mounted","returncode":0,"data":{}}','',0)
    app.state.resource_transport=transport
    response=begin(admin,c,'mount.create',dict(machine_id=m['id'],target_user='test',fs_name='fs',mount_path='/mnt/auth-batch',count=3))
    assert response.status_code==202,response.text
    oid=response.json()['id']
    assert admin.get('/api/v1/resource-operations/'+oid).json()['state']=='needs_password'
    assert admin.post('/api/v1/resource-operations/'+oid+'/cancel').json()['state']=='cancelled'
    assert [r['state'] for r in sorted(resources(admin,c),key=lambda r:r['name'])]==['mounted','unknown','not_started']


@pytest.mark.parametrize('count', [33, 100, 1000])
def test_positive_batch_counts_above_old_limit(count):
    p=dict(machine_id='node',target_user='test',fs_name='fs',mount_path='/mnt/test')
    assert schemas.validate('mount.create',{**p,'count':count})['count']==count
    template=dict(machine_id='node',target_user='test',listen_ip='192.0.2.1',cache_dir='/mnt/cache',port_mode='auto')
    assert schemas.validate('cache.plan',{'group_name':'g','members':[template],'count':count})['count']==count
    assert len(schemas.validate('cache.plan',{'group_name':'g','members':[template]*count})['members'])==count
