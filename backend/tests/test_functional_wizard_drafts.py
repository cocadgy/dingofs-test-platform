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
