from uuid import uuid4
import pytest
from conftest import linked
from test_storage_profiles import login
from test_resource_api import port_runner, runner  # noqa: F401
from dingofs_platform.resources.models import ResourceOperation

URL='/api/v1/cache-profiles'
def body(**kw): return {**dict(name='通用缓存',description='test',parameters={'shards':'4','cache_eviction':'lru'},enabled=True),**kw}
def add(client, **kw):
    r=client.post(URL,json=body(**kw)); assert r.status_code==201,r.text
    return r.json()

def test_crud_permissions_revisions_and_soft_delete(admin):
    owner=add(admin)
    login(admin,'member')
    listing=admin.get(URL).json()
    assert listing[0]['can_manage'] is False
    assert admin.put(URL+'/'+owner['id'],json={**body(),'revision':1}).status_code==403
    assert admin.delete(URL+'/'+owner['id']+'?revision=1').status_code==403
    own=add(admin,name='我的缓存')
    update={**body(),'name':'我的缓存','revision':1,'enabled':False}
    assert admin.put(URL+'/'+own['id'],json=update).json()['revision']==2
    assert admin.put(URL+'/'+own['id'],json=update).status_code==409
    login(admin,'admin')
    assert all(p['can_manage'] for p in admin.get(URL).json())
    assert admin.delete(URL+'/'+own['id']+'?revision=2').status_code==204
    assert len(admin.get(URL).json())==1
    assert admin.post(URL,json=body()).status_code==409

@pytest.mark.parametrize('parameters',[{'id':'../injected'},{'daemonize':'false'},{'shards':'-1'},{'s3_ak':'secret'}])
def test_profile_rejects_invalid_parameters(admin,parameters):
    assert admin.post(URL,json={**body(),'parameters':parameters}).status_code==422

def start(client,c,profile,parameters=None):
    return client.post('/api/v1/clusters/'+c['id']+'/resource-operations',json={
      'action':'cache.plan','base_revision':c['revision'],'request_id':str(uuid4()),'confirmed':True,
      'parameters':{'group_name':'g','cache_profile_id':profile['id'],'cache_profile_revision':profile['revision'],**(parameters or {})}})

def test_template_override_is_snapshotted_and_plan_consumes_same_values(admin,app,port_runner):
    m,c,_=linked(admin)
    profile=add(admin)
    params={'cache_options':{'shards':'2','cache_expire_s':'0','cache_size_mb':'2048'},'members':[{'machine_id':m['id'],'target_user':'test','listen_ip':'10.0.0.1','port_mode':'auto','cache_dir':'/mnt/cache'}]}
    r=start(admin,c,profile,params);assert r.status_code==202,r.text
    oid=r.json()['id']
    with app.state.session_factory() as db:
        op=db.get(ResourceOperation,oid)
        assert op.state=='succeeded',op.result
        record=op.steps[0]['record']
        assert record['cache_options']=={'shards':'2','cache_expire_s':'0'}
        assert record['cache_size_mb']==2048
    assert admin.get(URL).json()[0]['parameters']['shards']=='4'
    assert admin.put(URL+'/'+profile['id'],json={**body(),'parameters':{'shards':'8'},'revision':1}).status_code==200
    response=admin.post('/api/v1/clusters/'+c['id']+'/resource-operations',json={'action':'cache.create','base_revision':c['revision'],'request_id':str(uuid4()),'confirmed':True,'parameters':{'plan_id':oid}})
    assert response.status_code==202,response.text
    assert port_runner[-1]['record']['cache_options']['shards']=='2'

def test_disabled_and_stale_templates_fail_before_execution(admin,app,port_runner):
    m,c,_=linked(admin);profile=add(admin)
    params={'members':[{'machine_id':m['id'],'target_user':'test','listen_ip':'10.0.0.1','cache_dir':'/mnt/cache'}]}
    changed=admin.put(URL+'/'+profile['id'],json={**body(),'revision':1,'enabled':False}).json()
    assert start(admin,c,profile,params).status_code==409
    assert start(admin,c,changed,params).status_code==422
    assert not port_runner

def test_template_defaults_used_without_explicit_options(admin,app,port_runner):
    m,c,_=linked(admin)
    profile=add(admin)
    params={'members':[{'machine_id':m['id'],'target_user':'test','listen_ip':'10.0.0.1','cache_dir':'/mnt/cache','cache_size_mb':512}]}
    r=start(admin,c,profile,params);assert r.status_code==202,r.text
    assert port_runner[0]['record']['cache_options']['shards']=='4'
    assert port_runner[0]['record']['cache_size_mb']==512
    catalog=admin.get(URL+'/catalog').json()
    assert len(catalog['fields'])==94 and catalog['source_version']=='main-fe4384a0b'


def test_rdma_template_incomplete_combination_returns_validation_error(admin,app,port_runner):
    m,c,_=linked(admin)
    profile=add(admin,parameters={'use_rdma':'true'})
    params={'members':[{'machine_id':m['id'],'target_user':'test','listen_ip':'10.0.0.1','cache_dir':'/mnt/cache'}]}
    result=start(admin,c,profile,params)
    assert result.status_code==422, result.text
    assert 'RDMA' in result.json()['message']
    assert not port_runner
