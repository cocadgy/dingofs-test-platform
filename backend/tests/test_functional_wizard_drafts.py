from conftest import linked

BASE='/api/v1/functional/drafts'

def test_draft_round_trip_conflict_and_secret_rejection(admin,app):
    machine,cluster,_=linked(admin)
    body={'name':'临时测试','step':2,'configuration':{'cluster_id':cluster['id'],'machine_id':machine['id'],'fs_mode':'auto'}}
    created=admin.post(BASE,json=body)
    assert created.status_code==201,created.text
    row=created.json();assert row['revision']==1 and row['step']==2
    found=admin.get(BASE).json();assert any(x['id']==row['id'] for x in found)
    assert admin.put(BASE+'/'+row['id'],json={**body,'revision':2}).status_code==409
    updated=admin.put(BASE+'/'+row['id'],json={**body,'revision':1,'step':4})
    assert updated.status_code==200,updated.text
    assert updated.json()['revision']==2 and updated.json()['step']==4
    assert admin.put(BASE+'/'+row['id'],json={**body,'revision':2,'configuration':{'ssh_password':'secret'}}).status_code==422
    assert admin.delete(BASE+'/'+row['id']+'?revision=2').status_code==204
    assert admin.get(BASE+'/'+row['id']).status_code==404

def test_draft_is_private_to_owner(admin,app):
    body={'name':'private','step':1,'configuration':{'cluster_id':'c'}}
    row=admin.post(BASE,json=body).json()
    admin.post('/api/v1/auth/login',json={'username':'member','password':'test-password-123'})
    assert admin.get(BASE+'/'+row['id']).status_code==404


def test_guided_draft_rejects_unknown_fields_and_nested_identity_secret(admin):
    valid={'kind':'existing-environments','version':2,'cluster_id':'cluster-1',
           'default_environment_id':'env-1','module_plans':[],
           'name':'功能测试','retries':0,'timeout_minutes':1440}
    body={'name':'功能测试','step':1,'configuration':valid}
    created=admin.post(BASE,json=body)
    assert created.status_code==201,created.text
    assert created.json()['configuration']==valid
    for change in ({'machine_id':'other'},
                   {'run_as_user':'test/secret'},
                   {'module_plans':[{'module':'quota','cases':['case.yaml'],
                                     'environment_profile_id':'env-1',
                                     'environment_profile_revision':1,
                                     'run_as_user':'test/secret'}]}):
        invalid=admin.post(BASE,json={**body,'configuration':{**valid,**change}})
        assert invalid.status_code==422,invalid.text


def test_guided_draft_conflict_never_overwrites_and_legacy_remains_legacy(admin):
    legacy={'name':'旧草稿','step':5,'configuration':{'cluster_id':'old','fs_mode':'auto'}}
    old=admin.post(BASE,json=legacy)
    assert old.status_code==201,old.text
    assert admin.get(BASE+'/'+old.json()['id']).json()['configuration']==legacy['configuration']
    guided={'name':'新草稿','step':2,'configuration':{'kind':'existing-environments','version':2,
        'cluster_id':'c','default_environment_id':'e','module_plans':[],
        'name':'新草稿','retries':0,'timeout_minutes':1440}}
    row=admin.post(BASE,json=guided).json()
    changed=admin.put(BASE+'/'+row['id'],json={**guided,'step':3,'revision':1})
    assert changed.status_code==200,changed.text
    stale=admin.put(BASE+'/'+row['id'],json={**guided,'name':'stale','revision':1})
    assert stale.status_code==409,stale.text
    fresh=admin.get(BASE+'/'+row['id']).json()
    assert fresh['name']=='新草稿' and fresh['step']==3 and fresh['revision']==2
