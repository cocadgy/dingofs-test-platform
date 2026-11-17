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
    with app.state.session_factory.begin() as db:db.get(Cluster,cluster['id']).status_snapshot={'mds_addresses':['10.0.0.1:6900']}
    payload={'name':'lifecycle','cluster_id':cluster['id'],'env_name':'env_test',
             'selected':{'basic_file_operation':['a.yaml','b.yaml']},'catalog_digest':catalogue(root.parent)['digest']}
    return payload,machine,cluster

def create(admin,ready):
    r=admin.post('/api/v1/functional/runs',json=ready[0]);assert r.status_code==202,r.text
    return r.json()

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
