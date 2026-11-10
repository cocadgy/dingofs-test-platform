"""API and worker lifecycle checks use the isolated test database only."""
import pytest
from conftest import linked
from dingofs_platform.functional.catalog import catalogue
from dingofs_platform.functional.models import FunctionalRun
from dingofs_platform.inventory.models import Cluster

@pytest.fixture
def ready(admin,app,tmp_path):
    machine,cluster,_=linked(admin)
    root=tmp_path/'testcases'/'basic_file_operation';root.mkdir(parents=True)
    for name in ('a','b'):(root/(name+'.yaml')).write_text('case_name: '+name+'\nsteps: []\n')
    app.state.settings.functional_source_root=root.parent
    env_root=root.parent.parent/'conf'/'env';env_root.mkdir(parents=True)
    (env_root/'test.yaml').write_text('env_test:\n  mds_addr: 10.0.0.1:6900\n  storage: {storage_type: s3}\n  clients:\n    - host: '+machine['address']+'\n')
    (env_root.parent/'storage.yaml').write_text('s3: {}\n')
    from sqlalchemy import select
    from dingofs_platform.functional.environments.service import sync_predefined
    from dingofs_platform.functional.environments.models import FunctionalEnvironmentProfile
    with app.state.session_factory.begin() as db:
        db.get(Cluster,cluster['id']).status_snapshot={'mds_addresses':['10.0.0.1:6900']}
        sync_predefined(db, env_root)
        profile=db.scalar(select(FunctionalEnvironmentProfile).where(FunctionalEnvironmentProfile.source_key=='env_test'))
        profile_id, profile_revision=profile.id, profile.revision
    payload={'name':'lifecycle','cluster_id':cluster['id'],
             'environment_profile_id':profile_id,'environment_profile_revision':profile_revision,
             'selected':{'basic_file_operation':['a.yaml','b.yaml']},'catalog_digest':catalogue(root.parent)['digest']}
    return payload,machine,cluster

def create(admin,ready):
    r=admin.post('/api/v1/functional/runs',json=ready[0]);assert r.status_code==202,r.text
    return r.json()


def test_legacy_submission_checks_shared_conflict_service(admin, app, ready):
    from dingofs_platform.operations.leases import acquire_leases, LeaseRequest
    with app.state.session_factory.begin() as db:
        acquire_leases(db, 'resource:other', [LeaseRequest('cluster:' + ready[2]['id'])])
    response = admin.post('/api/v1/functional/runs', json=ready[0])
    assert response.status_code == 409
    assert response.json()['code'] == 'operation_conflict'


def test_legacy_worker_rechecks_lease_before_remote_launch(admin, app, ready):
    from dingofs_platform.operations.leases import acquire_leases, LeaseRequest
    row = create(admin, ready)
    with app.state.session_factory.begin() as db:
        acquire_leases(db, 'resource:other', [LeaseRequest('cluster:' + ready[2]['id'])])
    class Forbidden:
        def __init__(self, *args): raise AssertionError('must wait for target leases')
    app.state.functional_transport = Forbidden
    app.state.functional_manager.process(row['id'])
    assert admin.get('/api/v1/functional/runs/' + row['id']).json()['state'] == 'queued'


def test_legacy_unresolved_environment_cannot_be_submitted(admin, app, ready):
    payload = {key:value for key,value in ready[0].items() if not key.startswith('environment_profile_')}
    response = admin.post('/api/v1/functional/runs', json={**payload, 'env_name':'env_missing'})
    assert response.status_code == 422
    assert response.json()['code'] == 'target_unresolved'


def test_bare_env_local_yaml_never_proves_remote_targets(admin, app, ready):
    from datetime import timedelta
    from dingofs_platform.functional.manager import now
    from dingofs_platform.auth.models import User
    from sqlalchemy import select
    payload = {key:value for key,value in ready[0].items() if not key.startswith('environment_profile_')}
    payload['env_name']='env_test'
    response = admin.post('/api/v1/functional/runs', json=payload)
    assert response.status_code == 422
    assert response.json()['code'] == 'target_unresolved'
    # Historical records remain readable but cannot launch based on local YAML.
    with app.state.session_factory.begin() as db:
        actor = db.scalar(select(User).where(User.username=='admin'))
        m=ready[1]
        row=FunctionalRun(creator_id=actor.id,cluster_id=ready[2]['id'],machine_id=m['id'],
            name='historical',deadline=now()+timedelta(minutes=5),snapshot={**payload,
                'connection':[m['address'],m['ssh_port'],m['ssh_user']]})
        db.add(row);db.flush();oid=row.id
    class Forbidden:
        def __init__(self, config): raise AssertionError('unbound legacy source must never connect')
    app.state.functional_transport=Forbidden
    app.state.functional_manager.process(oid)
    detail=admin.get('/api/v1/functional/runs/'+oid).json()
    assert detail['state']=='failed'
    assert 'target_unresolved' in detail['error']


def test_legacy_completion_without_recovery_requires_attention(admin, app, ready):
    from dingofs_platform.operations.leases import check_conflicts, LeaseRequest
    row = create(admin, ready)
    class Done:
        def __init__(self, config): pass
        def start(self, payload): return {'root':'/tmp/functional-job'}
        def poll(self, id, cancel): return {'state':'success', 'result':{'cases':[]}}
    app.state.functional_transport = Done
    app.state.functional_manager.process(row['id'])
    result = admin.get('/api/v1/functional/runs/' + row['id']).json()
    assert result['state'] == 'needs_attention'
    assert '复核' in result['phase']
    with app.state.session_factory() as db:
        assert check_conflicts(db, [LeaseRequest('cluster:' + ready[2]['id'])])

@pytest.mark.parametrize('mutation,expected',[
 ({'selected':{}},422),({'selected':{'basic_file_operation':['../a.yaml']}},422),
 ({'selected':{'basic_file_operation':['a.yaml','a.yaml']}},422),
 ({'catalog_digest':'0'*64},409),({'timeout_minutes':0},422),({'retries':6},422),
 ({'binaries':{'dingo-client':'relative/path'}},422),
 ({'binaries':{'dingo-client':'/tmp/../bin/client'}},422)])
def test_invalid_submission_never_creates_task(admin,app,ready,mutation,expected):
    assert admin.post('/api/v1/functional/runs',json={**ready[0],**mutation}).status_code==expected
    assert admin.get('/api/v1/functional/runs').json()==[]

def test_duplicate_stop_and_finished_stop(admin,app,ready):
    row=create(admin,ready);url='/api/v1/functional/runs/'+row['id']
    assert admin.post('/api/v1/functional/runs',json=ready[0]).status_code==409
    assert admin.post(url+'/rerun').status_code==409
    assert admin.post(url+'/stop').json()['cancel_requested']
    with app.state.session_factory.begin() as db:db.get(FunctionalRun,row['id']).state='cancelled'
    assert admin.post(url+'/stop').status_code==409

def test_failed_only_rerun_uses_only_final_failed_cases(admin,app,ready):
    row=create(admin,ready)
    with app.state.session_factory.begin() as db:
        old=db.get(FunctionalRun,row['id']);old.state='failed';old.result={'cases':[
          {'module':'basic_file_operation','case':'a.yaml','status':'PASS'},
          {'module':'basic_file_operation','case':'b.yaml','status':'FAIL'}]}
    r=admin.post('/api/v1/functional/runs/'+row['id']+'/rerun?failed_only=true')
    assert r.status_code==202,r.text
    assert r.json()['snapshot']['selected']=={'basic_file_operation':['b.yaml']}
    assert r.json()['snapshot']['rerun_of']==row['id']

def test_success_has_no_failed_rerun_and_all_rerun_is_exact(admin,app,ready):
    row=create(admin,ready)
    with app.state.session_factory.begin() as db:db.get(FunctionalRun,row['id']).state='success'
    url='/api/v1/functional/runs/'+row['id']
    assert admin.post(url+'/rerun?failed_only=true').status_code==422
    r=admin.post(url+'/rerun');assert r.status_code==202,r.text
    assert r.json()['snapshot']['selected']==ready[0]['selected']

def test_member_cannot_read_stop_rerun_or_fetch_other_users_report(admin,app,ready):
    row=create(admin,ready);url='/api/v1/functional/runs/'+row['id']
    login=admin.post('/api/v1/auth/login',json={'username':'member','password':'test-password-123'})
    admin.headers['X-CSRF-Token']=login.json()['csrf_token']
    assert admin.get('/api/v1/functional/runs').json()==[]
    for method,path in [('GET',url),('POST',url+'/stop'),('POST',url+'/rerun'),('GET',url+'/report/index.html')]:
        assert admin.request(method,path).status_code==403

def test_queued_cancel_never_connects_to_remote(admin,app,ready):
    row=create(admin,ready);admin.post('/api/v1/functional/runs/'+row['id']+'/stop')
    def forbidden(*args):raise AssertionError('cancelled queued task connected remotely')
    app.state.functional_transport=forbidden
    app.state.functional_manager.process(row['id'])
    assert admin.get('/api/v1/functional/runs/'+row['id']).json()['state']=='cancelled'

@pytest.mark.parametrize('state',['running','unknown'])
def test_resumed_poll_failure_keeps_unknown_and_blocks_relaunch(admin,app,ready,state):
    row=create(admin,ready)
    with app.state.session_factory.begin() as db:db.get(FunctionalRun,row['id']).state=state
    class Offline:
        def __init__(self,*args):pass
        def start(self,*args):raise AssertionError('must not launch resumed task')
        def poll(self,*args):raise TimeoutError('temporary SSH outage')
    app.state.functional_transport=Offline
    app.state.functional_manager.process(row['id'])
    result=admin.get('/api/v1/functional/runs/'+row['id']).json()
    assert result['state']=='unknown'
    assert result['finished_at'] is None
    assert admin.post('/api/v1/functional/runs',json=ready[0]).status_code==409

@pytest.mark.parametrize('fallback',[False,True])
def test_report_missing_is_404_and_legacy_module_report_is_readable(admin,app,ready,tmp_path,monkeypatch,fallback):
    import contextlib,io,json
    from pathlib import Path
    from unittest.mock import patch
    row=create(admin,ready)
    if fallback:
        report=tmp_path/'.local/share/dingofs-platform/functional'/row['id']/'output/integration_old/basic_file_operation/allure-report-latest/index.html'
        report.parent.mkdir(parents=True);report.write_text('<html>real failed report</html>')
    class LocalRemote:
        def __init__(self,*args):pass
        def python(self,code,*args,**kwargs):
            output=io.StringIO()
            with patch.object(Path,'home',return_value=tmp_path),contextlib.redirect_stdout(output):exec(code,{})
            return json.loads(output.getvalue())
        def close(self):pass
    monkeypatch.setattr('dingofs_platform.functional.routes.Remote',LocalRemote)
    r=admin.get('/api/v1/functional/runs/'+row['id']+'/report/index.html')
    assert r.status_code==(200 if fallback else 404),r.text
    if fallback:assert 'real failed report' in r.text


def test_catalog_change_blocks_rerun(admin,app,ready):
    row=create(admin,ready)
    with app.state.session_factory.begin() as db:db.get(FunctionalRun,row['id']).state='success'
    (app.state.settings.functional_source_root/'basic_file_operation/a.yaml').write_text('case_name: changed\nsteps: []\n')
    assert admin.post('/api/v1/functional/runs/'+row['id']+'/rerun').status_code==409


def test_csrf_is_required_before_task_creation(admin,app,ready):
    admin.headers.pop('X-CSRF-Token',None)
    assert admin.post('/api/v1/functional/runs',json=ready[0]).status_code==403
    assert admin.get('/api/v1/functional/runs').json()==[]
