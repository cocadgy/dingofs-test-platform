from conftest import machine
from dingofs_platform.tool_packages.models import ToolJob
from datetime import datetime, timezone, timedelta


def test_runtime_lease_blocks_install_but_check_is_readonly(admin):
    from test_performance_api import setup
    from dingofs_platform.operations.leases import acquire_leases, LeaseRequest
    payload = setup(admin)
    mid = payload['machine_id']
    with admin.app.state.session_factory.begin() as db:
        acquire_leases(db, 'functional:other', [LeaseRequest('runtime:' + mid, 'shared')])
    response = admin.post('/api/v1/machines/' + mid + '/tool-jobs', json={'action':'install', 'package_id':'unused'})
    assert response.status_code == 409
    assert response.json()['code'] == 'operation_conflict'
    admin.app.state.tool_transport = lambda *args: {'items': []}
    response = admin.post('/api/v1/machines/' + mid + '/tool-jobs', json={'action':'check'})
    assert response.status_code == 202, response.text
    assert admin.get('/api/v1/machines/' + mid + '/tool-jobs').json()[0]['state'] == 'success'


def test_tool_execution_checks_conflicts_before_install(admin):
    from test_performance_api import setup
    from dingofs_platform.operations.leases import acquire_leases, LeaseRequest
    from dingofs_platform.tool_packages.service import run_job
    from dingofs_platform.inventory.ssh_transport import SSHConfig
    payload = setup(admin)
    with admin.app.state.session_factory.begin() as db:
        row = ToolJob(machine_id=payload['machine_id'], creator_id='test', action='install',
                      deadline=datetime.now(timezone.utc) + timedelta(minutes=5))
        db.add(row); db.flush(); oid = row.id
        acquire_leases(db, 'functional:other', [LeaseRequest('runtime:' + payload['machine_id'], 'shared')])
    admin.app.state.tool_transport = lambda *args: {'items': []}
    run_job(admin.app, oid, SSHConfig('example.test', 22, 'test', 'secret'))
    with admin.app.state.session_factory() as db:
        row = db.get(ToolJob, oid)
        assert row.state == 'failed'
        assert '占用' in row.result['error_message']


def test_auto_install_source_mutation_conflicts_at_submission_and_execution(admin):
    from test_performance_api import setup
    from dingofs_platform.operations.leases import acquire_leases, LeaseRequest
    from dingofs_platform.tool_packages.models import ToolSource
    from dingofs_platform.tool_packages.service import run_job
    from dingofs_platform.inventory.ssh_transport import SSHConfig
    payload = setup(admin)
    source = machine(admin, 'source')
    with admin.app.state.session_factory.begin() as db:
        db.add(ToolSource(id='default', machine_id=source['id'], directory='/tmp/tools', image='image:test', allow_cached=False))
        acquire_leases(db, 'functional:source-run', [LeaseRequest('runtime:' + source['id'], 'shared')])
        row = ToolJob(machine_id=payload['machine_id'], creator_id='test', action='auto_install',
            options={'tool':'dtt', 'source_machine_id':source['id']}, deadline=datetime.now(timezone.utc)+timedelta(minutes=5))
        db.add(row); db.flush(); oid = row.id
    response = admin.post('/api/v1/machines/' + payload['machine_id'] + '/tool-jobs', json={'action':'auto_install','tool':'dtt'})
    assert response.status_code == 409
    assert response.json()['code'] == 'operation_conflict'
    admin.app.state.tool_automatic_transport = lambda *args: {'items': []}
    run_job(admin.app, oid, SSHConfig('target.test', 22, 'test', 'secret'))
    with admin.app.state.session_factory() as db:
        row = db.get(ToolJob, oid)
        assert row.state == 'failed'
        assert '占用' in row.result['error_message']


def test_readonly_tool_check_can_continue_during_install(admin):
    from test_performance_api import setup
    from dingofs_platform.operations.leases import acquire_leases, LeaseRequest
    payload = setup(admin)
    with admin.app.state.session_factory.begin() as db:
        db.add(ToolJob(machine_id=payload['machine_id'], creator_id='test', action='install',
            deadline=datetime.now(timezone.utc)+timedelta(minutes=5)))
        acquire_leases(db, 'tool:install', [LeaseRequest('runtime:' + payload['machine_id'])])
    admin.app.state.tool_transport = lambda *args: {'items': []}
    response = admin.post('/api/v1/machines/' + payload['machine_id'] + '/tool-jobs', json={'action':'check'})
    assert response.status_code == 202, response.text


def test_member_cannot_publish_packages(client):
    response = client.post('/api/v1/auth/login', json={'username':'member', 'password':'test-password-123'})
    client.headers['X-CSRF-Token'] = response.json()['csrf_token']
    result = client.post('/api/v1/tool-packages', json={'directory':'v1'})
    assert result.status_code == 403


def test_machine_tool_job_requires_owner_and_credentials(admin):
    m = machine(admin)
    result = admin.post('/api/v1/machines/' + m['id'] + '/tool-jobs', json={'action':'check'})
    assert result.status_code == 422
    assert result.json()['code'] == 'ssh_password_missing'
    response = admin.post('/api/v1/auth/login', json={'username':'member', 'password':'test-password-123'})
    admin.headers['X-CSRF-Token'] = response.json()['csrf_token']
    assert admin.get('/api/v1/machines/' + m['id'] + '/tool-jobs').status_code == 200
    assert admin.post('/api/v1/machines/' + m['id'] + '/tool-jobs', json={'action':'check'}).status_code == 403


def test_expired_jobs_show_unknown_outcome(admin):
    m = machine(admin)
    with admin.app.state.session_factory.begin() as db:
        db.add(ToolJob(machine_id=m['id'], creator_id='test', action='check', deadline=datetime.now(timezone.utc)-timedelta(seconds=1)))
    result = admin.get('/api/v1/machines/' + m['id'] + '/tool-jobs').json()
    assert result[0]['state'] == 'interrupted'
    assert '重新检查' in result[0]['log']


def test_publish_and_deploy_records_progress_and_snapshot(admin, tmp_path):
    import hashlib
    import json
    from cryptography.fernet import Fernet
    from dingofs_platform.inventory.models import Machine
    from dingofs_platform.inventory.credentials import encrypt_password
    root = tmp_path/'release'
    root.mkdir()
    (root/'dingo').write_text('#!/bin/sh\necho version\n')
    manifest = {'tool':'dingo','version':'v1','architecture':'x86_64','entrypoint':'dingo','files':{'dingo':hashlib.sha256((root/'dingo').read_bytes()).hexdigest()}}
    (root/'manifest.json').write_text(json.dumps(manifest))
    admin.app.state.settings.tool_bundle_root = str(tmp_path)
    published = admin.post('/api/v1/tool-packages',json={'directory':'release'})
    assert published.status_code == 201, published.text
    m = machine(admin)
    admin.app.state.settings.credential_encryption_key = Fernet.generate_key().decode()
    with admin.app.state.session_factory.begin() as db:
        db.get(Machine,m['id']).ssh_password_ciphertext = encrypt_password('secret',admin.app.state.settings.credential_encryption_key)
    def transport(config,bundle,root,timeout,report):
        assert bundle['tool']=='dingo'
        assert config.username=='test'
        report(phase='传输',progress=50,message='SFTP dingo\n')
        return {'items':[{'tool':'dingo','status':'ready','path':'/home/test/.local/share/dingofs-platform/tools/dingo/current/dingo'}]}
    admin.app.state.tool_transport = transport
    result = admin.post('/api/v1/machines/'+m['id']+'/tool-jobs',json={'action':'install','package_id':published.json()['id']})
    assert result.status_code == 202, result.text
    job = admin.get('/api/v1/machines/'+m['id']+'/tool-jobs').json()[0]
    assert job['state']=='success'
    assert job['progress']==100
    assert job['result']['items'][0]['status']=='ready'
    assert 'secret' not in job['log']
    # A registered package cannot silently change underneath an install.
    (root/'dingo').write_text('modified')
    result = admin.post('/api/v1/machines/'+m['id']+'/tool-jobs',json={'action':'install','package_id':published.json()['id']})
    assert result.status_code==202
    assert admin.get('/api/v1/machines/'+m['id']+'/tool-jobs').json()[0]['state']=='failed'


def test_source_and_one_click_install_are_owned_and_snapshotted(admin):
    from cryptography.fernet import Fernet
    from dingofs_platform.inventory.models import Machine
    from dingofs_platform.inventory.credentials import encrypt_password
    m=machine(admin)
    admin.app.state.settings.credential_encryption_key=Fernet.generate_key().decode()
    with admin.app.state.session_factory.begin() as db:
        db.get(Machine,m['id']).ssh_password_ciphertext=encrypt_password('secret',admin.app.state.settings.credential_encryption_key)
    assert admin.get('/api/v1/tool-source').json()['configured'] is False
    saved=admin.put('/api/v1/tool-source',json={'machine_id':m['id']})
    assert saved.status_code==200,saved.text
    assert saved.json()['image']=='harbor.zetyun.cn/dingofs/dingofs-testsuite-tools:latest'
    def auto(target,source,options,timeout,report):
        assert options['tool']=='dtt'
        assert options['source_machine_id']==m['id']
        report(phase='目标机器拉取最新镜像',message='docker pull ...\n')
        return {'items':[],'method':'registry','cached':False}
    admin.app.state.tool_automatic_transport=auto
    result=admin.post('/api/v1/machines/'+m['id']+'/tool-jobs',json={'action':'auto_install','tool':'dtt'})
    assert result.status_code==202,result.text
    job=admin.get('/api/v1/machines/'+m['id']+'/tool-jobs').json()[0]
    assert job['state']=='success'
    assert job['result']['method']=='registry'
    def failing_auto(*args):
        raise RuntimeError('Cannot connect to Docker daemon; password=secret')
    admin.app.state.tool_automatic_transport=failing_auto
    admin.post('/api/v1/machines/'+m['id']+'/tool-jobs',json={'action':'auto_install','tool':'dtt'})
    failed=admin.get('/api/v1/machines/'+m['id']+'/tool-jobs').json()[0]
    assert failed['state']=='failed'
    assert 'Cannot connect to Docker daemon' in failed['result']['error_message']
    assert 'secret' not in failed['result']['error_message']
    login=admin.post('/api/v1/auth/login',json={'username':'member','password':'test-password-123'})
    admin.headers['X-CSRF-Token']=login.json()['csrf_token']
    assert admin.put('/api/v1/tool-source',json={'machine_id':m['id']}).status_code==403
    assert admin.post('/api/v1/machines/'+m['id']+'/tool-jobs',json={'action':'auto_install','tool':'dtt'}).status_code==403
