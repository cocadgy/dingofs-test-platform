from pathlib import Path
from conftest import linked
from dingofs_platform.functional.catalog import catalogue
from dingofs_platform.inventory.models import Cluster


def test_wizard_submission_uses_selected_machine_and_freezes_settings(admin,app,tmp_path):
    machine,cluster,_=linked(admin)
    root=tmp_path/'testcases'/'basic_file_operation'/'smoke';root.mkdir(parents=True)
    (root/'a.yaml').write_text('case_id: TC-X\ncase_name: simple\nrun_level: smoke\nsteps: []\n')
    app.state.settings.functional_source_root=tmp_path/'testcases'
    with app.state.session_factory.begin() as db:
        db.get(Cluster,cluster['id']).status_snapshot={'mds_addresses':['10.0.0.1:6900']}
    storage=admin.post('/api/v1/storage-profiles',json={'name':'wizard-storage','storage_type':'s3','parameters':{
        's3_ak':'private-ak','s3_sk':'private-sk','s3_endpoint':'http://s3','s3_bucketname':'bucket'},'enabled':True,'description':''}).json()
    digest=catalogue(tmp_path/'testcases')['digest']
    draft=admin.post('/api/v1/functional/drafts',json={'name':'draft','step':6,'configuration':{'cluster_id':cluster['id'],'machine_id':machine['id']}}).json()
    body={'name':'wizard-run','cluster_id':cluster['id'],'selected':{'basic_file_operation':['smoke/a.yaml']},'catalog_digest':digest,
      'wizard':{'machine_id':machine['id'],'storage_profile_id':storage['id'],'settings':{'mount_root':'/tmp/wizard','fs_prefix':'wizardfs'},'fs_mode':'auto'},
      'draft_id':draft['id'],'draft_revision':draft['revision']}
    assert admin.post('/api/v1/functional/runs',json={**body,'wizard':{**body['wizard'],'settings':{'ssh_password':'leak'}}}).status_code==422
    response=admin.post('/api/v1/functional/runs',json=body)
    assert response.status_code==202,response.text
    row=response.json()
    assert row['machine_id']==machine['id']
    assert row['snapshot']['environment_profile_snapshot']['settings']['mount_root']=='/tmp/wizard'
    assert 'private-sk' not in str(row)
    assert all(r['id']!=draft['id'] for r in admin.get('/api/v1/functional/drafts').json())
