from pathlib import Path
from conftest import linked

URL='/api/v1/functional/environments'

def test_sync_is_idempotent_and_presets_have_no_secrets(admin, app, tmp_path):
    root=tmp_path/'conf'/'env';root.mkdir(parents=True)
    (root/'one.yaml').write_text('env_base:\n  run_as_user: root/supersecret\n  mds_addr: 10.0.0.1:6900\n  storage: {storage_type: s3}\n  clients: [{host: node, mount_path: /mnt/x}]\n')
    app.state.settings.functional_source_root=root.parent.parent/'testcases'
    for _ in range(2):
        result=admin.post(URL+'/sync-predefined')
        assert result.status_code==200,result.text
    rows=admin.get(URL).json();assert len(rows)==1
    assert rows[0]['source_kind']=='predefined'
    assert 'supersecret' not in str(rows)
    from sqlalchemy import select
    from dingofs_platform.functional.environments.models import FunctionalEnvironmentProfile
    from dingofs_platform.audit.models import AuditEvent
    with app.state.session_factory() as db:
        stored=str([(r.settings,r.display) for r in db.scalars(select(FunctionalEnvironmentProfile))])
        audited=str([r.detail for r in db.scalars(select(AuditEvent))])
    assert 'supersecret' not in stored+audited

def test_custom_environment_crud_permissions_and_revision(admin, app):
    machine,cluster,_=linked(admin)
    body={'name':'fresh-test','cluster_id':cluster['id'],'machine_id':machine['id'],
          'storage_profile_id':None,'settings':{'mount_root':'/tmp/functional','fs_prefix':'test'},'enabled':True}
    result=admin.post(URL,json=body)
    assert result.status_code==201,result.text
    row=result.json();assert row['revision']==1
    assert admin.put(URL+'/'+row['id'],json={**body,'revision':2}).status_code==409
    assert admin.put(URL+'/'+row['id'],json={**body,'revision':1,'name':'changed'}).status_code==200
    assert admin.get(URL+'/'+row['id']).json()['name']=='changed'

def test_member_cannot_use_another_users_machine_or_sync(admin, app):
    machine,cluster,_=linked(admin)
    login=admin.post('/api/v1/auth/login',json={'username':'member','password':'test-password-123'})
    admin.headers['X-CSRF-Token']=login.json()['csrf_token']
    assert admin.post(URL+'/sync-predefined').status_code==403
    body={'name':'other-machine','cluster_id':cluster['id'],'machine_id':machine['id'],
          'storage_profile_id':None,'settings':{'mount_root':'/tmp/test','fs_prefix':'test'},'enabled':True}
    assert admin.post(URL,json=body).status_code==403

def test_predefined_source_change_updates_revision_without_secret(admin, app, tmp_path):
    root=tmp_path/'conf'/'env';root.mkdir(parents=True)
    path=root/'source.yaml'
    path.write_text('env_example:\n  mds_addr: 10.0.0.1:6900\n  clients: [{host: node}]\n  storage: {storage_type: s3}\n  run_as_user: root/private-a\n')
    app.state.settings.functional_source_root=root.parent.parent/'testcases'
    assert admin.post(URL+'/sync-predefined').status_code==200
    original=admin.get(URL).json()[0]
    path.write_text(path.read_text().replace('private-a','private-b'))
    assert admin.post(URL+'/sync-predefined').status_code==200
    updated=admin.get(URL).json()[0]
    assert updated['id']==original['id'] and updated['revision']==2
    assert 'private-b' not in str(updated)

def test_duplicate_name_copy_and_missing_source(admin,app,tmp_path):
    machine,cluster,_=linked(admin)
    root=tmp_path/'conf'/'env';root.mkdir(parents=True)
    source=root/'one.yaml'
    source.write_text('env_existing:\n  mds_addr: 10.0.0.1:6900\n  clients: [{host: node}]\n  storage: {storage_type: s3}\n')
    app.state.settings.functional_source_root=root.parent.parent/'testcases'
    assert admin.post(URL+'/sync-predefined').status_code==200
    preset=admin.get(URL).json()[0]
    body={'name':'copy-of-existing','cluster_id':cluster['id'],'machine_id':machine['id'],
          'storage_profile_id':None,'settings':{'mount_root':'/tmp/test','fs_prefix':'test'},'enabled':True}
    copied=admin.post(URL+'/'+preset['id']+'/copy',json=body)
    assert copied.status_code==201,copied.text
    assert copied.json()['source_kind']=='custom' and copied.json()['source_file'] is None
    assert admin.post(URL,json=body).status_code==409
    source.unlink()
    assert admin.post(URL+'/sync-predefined').status_code==200
    old=admin.get(URL+'/'+preset['id']).json()
    assert old['enabled'] is False and old['validation']=='source_missing'

def test_disabled_storage_profile_is_rejected(admin,app):
    machine,cluster,_=linked(admin)
    storage=admin.post('/api/v1/storage-profiles',json={'name':'disabled-backend','storage_type':'s3',
      'parameters':{'s3_ak':'private-ak','s3_sk':'private-sk','s3_endpoint':'http://s3','s3_bucketname':'bucket'},
      'enabled':False,'description':''})
    assert storage.status_code==201,storage.text
    response=admin.post(URL,json={'name':'cannot-run','cluster_id':cluster['id'],'machine_id':machine['id'],
      'storage_profile_id':storage.json()['id'],'settings':{'mount_root':'/tmp/test','fs_prefix':'test'},'enabled':True})
    assert response.status_code==422
    assert 'private-ak' not in response.text and 'private-sk' not in response.text

def test_custom_environment_rejects_unknown_member_machine(admin,app):
    machine,cluster,_=linked(admin)
    body={'name':'unknown-cache-host','cluster_id':cluster['id'],'machine_id':machine['id'],
          'storage_profile_id':None,'settings':{'mount_root':'/tmp/test','fs_prefix':'test',
          'clients':[{'machine_id':machine['id'],'client_count':2}],
          'remote_caches':[{'machine_id':'00000000-0000-0000-0000-000000000000','remote_cache_count':1}]},'enabled':True}
    result=admin.post(URL,json=body)
    assert result.status_code==422,result.text
    assert '客户端或缓存成员机器不可用' in result.text

def test_copy_settings_preserve_inherited_members_without_credentials(admin,app,tmp_path):
    root=tmp_path/'conf'/'env';root.mkdir(parents=True)
    (root/'source.yaml').write_text('''base:
  run_as_user: root/private-password
  mds_addr: 10.0.0.1:6900
  storage: {storage_type: s3, s3: {s3_sk: private-key}}
  clients:
    - host: old-host
      mount_path: /mnt/original
      client_count: 3
      client_conf: {--use_rdma: true}
  remote_caches:
    - host: cache-host
      remote_cache_count: 4
      remote_cache_conf: {--cache_dir: /cache, --cache_size_mb: 4096, --mds_addrs: old-mds}
env_child:
  base: base
  clients:
    - host: another-host
      client_conf: {--cache_group: example}
''')
    app.state.settings.functional_source_root=root.parent.parent/'testcases'
    assert admin.post(URL+'/sync-predefined').status_code==200
    row=next(r for r in admin.get(URL).json() if r['name']=='env_child')
    response=admin.get(URL+'/'+row['id']+'/copy-settings')
    assert response.status_code==200,response.text
    value=response.json();settings=value['settings']
    assert settings['clients'][0]['client_count']==3
    assert settings['clients'][0]['client_conf']=={'--use_rdma':True,'--cache_group':'example'}
    assert settings['clients'][0]['mount_path']=='/mnt/original'
    assert settings['clients'][0]['machine_id']==''
    assert settings['remote_caches'][0]['remote_cache_count']==4
    assert settings['remote_caches'][0]['remote_cache_conf']['--cache_size_mb']==4096
    assert '--mds_addrs' not in settings['remote_caches'][0]['remote_cache_conf']
    assert 'private-password' not in response.text and 'private-key' not in response.text
    (root/'source.yaml').write_text((root/'source.yaml').read_text().replace('4096','8192'))
    assert admin.get(URL+'/'+row['id']+'/copy-settings').status_code==409


def test_custom_environment_view_reports_real_member_counts(admin,app):
    machine,cluster,_=linked(admin)
    result=admin.post(URL,json={'name':'counts','cluster_id':cluster['id'],'machine_id':machine['id'],
      'settings':{'mount_root':'/tmp/test','fs_prefix':'test','clients':[{'machine_id':machine['id'],'client_count':3}],
      'remote_caches':[{'machine_id':machine['id'],'remote_cache_count':4}]},'enabled':True})
    assert result.status_code==201,result.text
    assert result.json()['display']['client_count']==3
    assert result.json()['display']['cache_count']==4
