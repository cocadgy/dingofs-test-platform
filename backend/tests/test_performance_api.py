from conftest import machine
from cryptography.fernet import Fernet
from dingofs_platform.inventory.models import Machine
from dingofs_platform.inventory.credentials import encrypt_password
from dingofs_platform.performance.models import PerformanceRun


def setup(admin):
    m=machine(admin)
    admin.app.state.settings.credential_encryption_key=Fernet.generate_key().decode()
    with admin.app.state.session_factory.begin() as db:
        db.get(Machine,m['id']).ssh_password_ciphertext=encrypt_password('secret',admin.app.state.settings.credential_encryption_key)
    return {'name':'benchmark','machine_id':m['id'],'target_path':'/tmp/perf','tests':[{'tool':'fio','file_size':'4KiB','file_count':1,'concurrency':1}]}


def test_create_preview_and_machine_exclusion(admin):
    payload=setup(admin)
    preview=admin.post('/api/v1/performance/preview',json=payload)
    assert preview.status_code==200,preview.text
    assert preview.json()['total_bytes']==4096
    result=admin.post('/api/v1/performance/runs',json=payload)
    assert result.status_code==202,result.text
    assert result.json()['state']=='queued'
    assert admin.post('/api/v1/performance/runs',json=payload).status_code==409
    assert admin.post('/api/v1/performance/runs/'+result.json()['id']+'/cancel').status_code==200
    admin.app.state.performance_manager.process(result.json()['id'])
    assert admin.get('/api/v1/performance/runs/'+result.json()['id']).json()['state']=='cancelled'


def test_member_cannot_execute_on_others_machine_or_cancel_task(admin):
    payload=setup(admin)
    row=admin.post('/api/v1/performance/runs',json=payload).json()
    login=admin.post('/api/v1/auth/login',json={'username':'member','password':'test-password-123'})
    admin.headers['X-CSRF-Token']=login.json()['csrf_token']
    assert admin.get('/api/v1/performance/runs').status_code==200
    assert admin.post('/api/v1/performance/preview',json=payload).status_code==403
    assert admin.post('/api/v1/performance/runs',json=payload).status_code==403
    assert admin.post('/api/v1/performance/runs/'+row['id']+'/cancel').status_code==403


def test_collection_and_html_report_isolation(admin):
    payload=setup(admin)
    result=admin.post('/api/v1/performance/runs',json=payload).json()
    class Fake:
        def __init__(self,config):pass
        def start(self,payload):return {'root':'/tmp/job'}
        def poll(self,id,cancel):return {'state':'success','phase':'完成','progress':100,'log':'tool done','reports':{'fio':{'summary':{'status':'passed'},'artifacts':{'index.html':'<script>alert(1)</script>','summary.json':'{}'}}}}
    admin.app.state.performance_transport=Fake
    admin.app.state.performance_manager.process(result['id'])
    detail=admin.get('/api/v1/performance/runs/'+result['id']).json()
    assert detail['state']=='success'
    assert detail['log']=='tool done'
    assert detail['reports']['fio']['files']==['index.html','summary.json']
    report=admin.get('/api/v1/performance/runs/'+result['id']+'/reports/fio/index.html')
    assert report.status_code==200
    assert 'sandbox allow-scripts;' in report.headers['content-security-policy']
    assert 'allow-same-origin' not in report.headers['content-security-policy']
    assert admin.get('/api/v1/performance/runs/'+result['id']+'/reports/fio/secret').status_code==404


def test_disconnection_does_not_restart_unknown_task(admin):
    payload=setup(admin)
    row=admin.post('/api/v1/performance/runs',json=payload).json()
    calls=[]
    class Fake:
        def __init__(self,c):pass
        def start(self,p):calls.append('start');raise OSError('connection lost')
        def poll(self,id,cancel):calls.append('poll');return {'missing':True}
    admin.app.state.performance_transport=Fake
    manager=admin.app.state.performance_manager
    manager.process(row['id']);manager.process(row['id'])
    assert calls==['start','poll']
    assert admin.get('/api/v1/performance/runs/'+row['id']).json()['state']=='unknown'


def test_matrix_preview_snapshot_and_transport_agree(admin):
    payload=setup(admin)
    payload['tests'][0].update(direct=[True,False],rw=['read','write'])
    payload['cleanup_data']=True
    preview=admin.post('/api/v1/performance/preview',json=payload)
    assert preview.status_code==200,preview.text
    scenes=preview.json()['tests']
    assert preview.json()['scene_count']==4
    assert preview.json()['total_bytes']==4*4096
    row=admin.post('/api/v1/performance/runs',json=payload).json()
    assert [s['parameters'] for s in scenes]==row['snapshot']['tests']
    assert [s['id'] for s in scenes]==[s['id'] for s in row['snapshot']['scenarios']]
    captured=[]
    class Fake:
        def __init__(self,config):pass
        def start(self,payload):captured.append(payload);return {'root':'/tmp/matrix'}
        def poll(self,id,cancel):return {'state':'failed','progress':100,'scene_results':{scenes[0]['id']:{'state':'failed','error':'fixture error'}}}
    admin.app.state.performance_transport=Fake
    admin.app.state.performance_manager.process(row['id'])
    assert captured[0]['cleanup_data'] is True
    assert [t['id'] for t in captured[0]['tests']]==[s['id'] for s in scenes]
    result=admin.get('/api/v1/performance/runs/'+row['id']).json()
    assert result['reports'][scenes[0]['id']]['state']=='failed'
    assert result['reports'][scenes[0]['id']]['error']=='fixture error'


def test_rerun_preserves_expanded_scenes_and_original_report(admin):
    payload=setup(admin);payload['tests'][0]['direct']=[True,False];payload['cleanup_data']=True
    original=admin.post('/api/v1/performance/runs',json=payload).json()
    with admin.app.state.session_factory.begin() as db:
        row=db.get(PerformanceRun,original['id']);row.state='failed';row.reports={'saved':{'artifacts':{'index.html':'old report'}}}
    result=admin.post('/api/v1/performance/runs/'+original['id']+'/rerun')
    assert result.status_code==202,result.text
    new=result.json()
    assert new['id']!=original['id']
    assert new['snapshot']['tests']==original['snapshot']['tests']
    assert new['snapshot']['rerun_of']==original['id']
    assert new['reports']=={}
    assert new['snapshot']['cleanup_data'] is True
    assert admin.get('/api/v1/performance/runs/'+original['id']+'/reports/saved/index.html').text=='old report'
    assert admin.post('/api/v1/performance/runs/'+original['id']+'/rerun').status_code==409


def test_rerun_requires_task_and_machine_permissions(admin):
    payload=setup(admin);original=admin.post('/api/v1/performance/runs',json=payload).json()
    with admin.app.state.session_factory.begin() as db:db.get(PerformanceRun,original['id']).state='failed'
    login=admin.post('/api/v1/auth/login',json={'username':'member','password':'test-password-123'})
    admin.headers['X-CSRF-Token']=login.json()['csrf_token']
    assert admin.post('/api/v1/performance/runs/'+original['id']+'/rerun').status_code==403
