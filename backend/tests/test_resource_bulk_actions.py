import json
import pytest
from conftest import linked
from test_resource_api import runner, begin
from test_resource_bulk_create import resources
from dingofs_platform.resources import schemas
from dingofs_platform.clusters.transport import ClusterCommandResult, ExecutionIdentity


def test_batch_targets_require_nonempty_unique_ids():
    for action, key in [('mount.unmount', 'resource_ids'), ('mount.delete', 'resource_ids'),
                        ('cache.stop', 'member_ids'), ('cache.delete_batch', 'member_ids')]:
        assert len(schemas.validate(action, {key: ['id'+str(i) for i in range(150)]})[key]) == 150
        for ids in [[], ['a','a'], ['']]:
            with pytest.raises(ValueError):
                schemas.validate(action, {key: ids})


@pytest.mark.parametrize('failed_index', [None, 1])
def test_batch_unmount_updates_each_resource(admin, app, runner, failed_index):
    m,c,_ = linked(admin)
    begin(admin,c,'mount.create',dict(machine_id=m['id'],target_user='test',fs_name='fs',mount_path='/mnt/batch',count=3))
    rows=resources(admin,c)
    calls=[]
    def transport(config,cmd,**kw):
        work=json.loads(cmd.resource_script); calls.append(work)
        failed=len(calls)-1==failed_index
        return ClusterCommandResult(ExecutionIdentity('test','/home/test','/bin/dingo'),
            json.dumps(dict(state='failed' if failed else 'unmounted', returncode=int(failed),
                            command_completed=True, message='busy' if failed else '', data={})), '', int(failed))
    app.state.resource_transport=transport
    response=begin(admin,c,'mount.unmount',{'resource_ids':[r['id'] for r in rows]})
    assert response.status_code==202,response.text
    op=admin.get('/api/v1/resource-operations/'+response.json()['id']).json()
    assert op['state']==('failed' if failed_index is not None else 'succeeded'),op
    assert len(calls)==3
    current={r['id']:r for r in resources(admin,c)}
    assert [current[r['id']]['state'] for r in rows]==['unknown' if i==failed_index else 'unmounted' for i in range(3)]
    assert [s['resource_id'] for s in op['result']['steps']]==[r['id'] for r in rows]
    assert all(call['action']=='mount.unmount' for call in calls)


def test_delete_rejects_mounted_and_validates_all_targets_first(admin,app,runner):
    m,c,_=linked(admin)
    begin(admin,c,'mount.create',dict(machine_id=m['id'],target_user='test',fs_name='fs',mount_path='/mnt/batch'))
    row=resources(admin,c)[0]
    before=len(runner)
    assert begin(admin,c,'mount.delete',{'resource_ids':[row['id']]}).status_code==409
    assert begin(admin,c,'mount.unmount',{'resource_ids':[row['id'],'missing']}).status_code==422
    assert len(runner)==before


def test_delete_unmounted_verifies_remote_and_preserves_other_records(admin,app,runner):
    m,c,_=linked(admin)
    begin(admin,c,'mount.create',dict(machine_id=m['id'],target_user='test',fs_name='fs',mount_path='/mnt/batch',count=2))
    rows=resources(admin,c)
    begin(admin,c,'mount.unmount',{'resource_ids':[r['id'] for r in rows]})
    response=begin(admin,c,'mount.delete',{'resource_ids':[rows[0]['id']]})
    assert response.status_code==202,response.text
    op=admin.get('/api/v1/resource-operations/'+response.json()['id']).json()
    assert op['state']=='succeeded',op
    current={r['id']:r for r in resources(admin,c)}
    assert current[rows[0]['id']]['state']=='deleted'
    assert current[rows[1]['id']]['state']=='unmounted'
    assert runner[-1]['action']=='mount.delete'
    assert runner[-1]['record']['mount_path']==rows[0]['name']


@pytest.mark.parametrize("mounted,running",[(True,False),(False,True),(False,False)])
def test_delete_never_unmounts_or_removes_data(monkeypatch,mounted,running):
    from dingofs_platform.resources import remote_helper as h
    process={'pid':123,'start_ticks':'1','exe':'/bin/dingo-client','argv':['dingo-client']}
    class Store:
        def __enter__(self): return self
        def __exit__(self,*a): pass
        def load(self): return {'process':process} if running else {}
    monkeypatch.setattr(h,'OwnedState',lambda *a,**k:Store())
    monkeypatch.setattr(h,'mounted',lambda p:mounted)
    monkeypatch.setattr(h,'process_identity',lambda p:process)
    monkeypatch.setattr(h,'run_command',lambda *a,**k:pytest.fail('must not execute unmount or delete files'))
    req={'action':'mount.delete','resource_id':'r','record':{'state_dir':'/state','mount_path':'/mount'}}
    if mounted or running:
        with pytest.raises(ValueError,match='still mounted or running'): h.lifecycle(req)
    else:
        assert h.lifecycle(req)==('deleted',{'mount_path':'/mount','data_preserved':True})


def test_mount_delete_script_uses_server_record():
    import shlex
    from dingofs_platform.resources.commands import build_script
    script=build_script('mount.delete',{'resource_id':'r'},'mds:6900','r',
                        record={'state_dir':'/state','log_dir':'/logs','mount_path':'/mount'})
    req=json.loads(shlex.split(script)[-1])
    assert req['action']=='mount.delete' and req['commands']==[]
    assert req['record']['mount_path']=='/mount'
