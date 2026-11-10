"""Guided UI read-only option and compatibility boundaries."""
from test_functional_preflight import ready  # noqa: F401 reuse isolated source/runtime fixture


def test_guided_metadata_exposes_gate_and_management_identity_without_install(admin, app, ready):
    response=admin.get('/api/v1/functional/guided/metadata')
    assert response.status_code==200,response.text
    value=response.json()
    assert value['enabled'] is True
    cluster=next(row for row in value['clusters'] if row['id']==ready[0].cluster_id)
    assert cluster['management_machine']=={
        'id':ready[3]['id'],'name':ready[3]['name'],
        'address':ready[3]['address'],'ssh_user':ready[3]['ssh_user']}
    assert any(machine['name']==ready[3]['name'] and machine['address']==ready[3]['address']
               and machine['ssh_user']==ready[3]['ssh_user'] for machine in value['machines'])
    assert ready[2].calls==[]


def test_guided_compatibility_checks_exact_cases_without_remote_calls(admin, app, ready):
    response=admin.post('/api/v1/functional/guided/compatibility',
                        json=ready[0].model_dump(mode='json'))
    assert response.status_code==200,response.text
    value=response.json()['modules']['quota']
    assert value['compatible'] is True
    assert value['reasons']==[]
    assert any(item['name']==ready[3]['name'] and item['address']==ready[3]['address']
               and item['user']==ready[3]['ssh_user'] for item in value['targets'])
    assert ready[2].calls==[]
