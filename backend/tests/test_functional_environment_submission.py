from conftest import linked
from dingofs_platform.functional.catalog import catalogue
from dingofs_platform.functional.models import FunctionalRun
from dingofs_platform.inventory.models import Cluster


def test_custom_submission_freezes_safe_profile_and_rejects_storage_change(admin,app,tmp_path):
    machine,cluster,_=linked(admin)
    root=tmp_path/'testcases'/'basic_file_operation'/'smoke';root.mkdir(parents=True)
    (root/'a.yaml').write_text('case_id: TC-X\ncase_name: simple\nrun_level: smoke\nsteps: []\n')
    app.state.settings.functional_source_root=tmp_path/'testcases'
    with app.state.session_factory.begin() as db:
        row=db.get(Cluster,cluster['id']);row.status_snapshot={'mds_addresses':['10.0.0.1:6900']}
    storage=admin.post('/api/v1/storage-profiles',json={'name':'test-storage','storage_type':'s3','parameters':{
        's3_ak':'secret-ak','s3_sk':'secret-sk','s3_endpoint':'http://s3','s3_bucketname':'bucket'},'enabled':True,'description':''})
    assert storage.status_code==201,storage.text
    profile=admin.post('/api/v1/functional/environments',json={'name':'new-machine','cluster_id':cluster['id'],
        'machine_id':machine['id'],'storage_profile_id':storage.json()['id'],
        'settings':{'mount_root':'/tmp/functional','fs_prefix':'test'},'enabled':True})
    assert profile.status_code==201,profile.text
    plan=catalogue(tmp_path/'testcases')
    payload={'name':'test','cluster_id':cluster['id'],'environment_profile_id':profile.json()['id'],
       'environment_profile_revision':profile.json()['revision'],'selected':{'basic_file_operation':['smoke/a.yaml']},
       'catalog_digest':plan['digest']}
    created=admin.post('/api/v1/functional/runs',json=payload)
    assert created.status_code==202,created.text
    snapshot=created.json()['snapshot']
    assert snapshot['env_name'].startswith('env_platform_')
    assert snapshot['environment_profile_snapshot']['storage_profile_revision']==1
    assert 'secret-ak' not in str(snapshot) and 'secret-sk' not in str(snapshot)
    with app.state.session_factory.begin() as db:db.get(FunctionalRun,created.json()['id']).state='success'
    changed=admin.put('/api/v1/storage-profiles/'+storage.json()['id'],json={'name':'test-storage','storage_type':'s3','parameters':{'s3_endpoint':'http://s3','s3_bucketname':'bucket'},'enabled':True,'description':'','revision':1})
    assert changed.status_code==200
    assert admin.post('/api/v1/functional/runs',json=payload).status_code==422
