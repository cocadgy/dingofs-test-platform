from cryptography.fernet import Fernet
from dingofs_platform.inventory.credentials import encrypt_password
from dingofs_platform.inventory.models import Machine
from test_asset_permissions import member_client
from test_cluster_discovery import transport, discover


def test_alias_defaults_to_machine_and_only_owner_or_admin_can_edit(app, admin):
    app.state.settings.credential_encryption_key = Fernet.generate_key().decode()
    app.state.cluster_transport = transport
    with member_client(app, 'aliasowner') as owner, member_client(app, 'aliasother') as other:
        m = owner.post('/api/v1/machines', json={
            'name': '测试机器', 'address': 'node.test', 'ssh_user': 'test',
        }).json()
        with app.state.session_factory.begin() as db:
            db.get(Machine, m['id']).ssh_password_ciphertext = encrypt_password('secret', app.state.settings.credential_encryption_key)
        op = discover(owner, m)
        response = owner.post('/api/v1/cluster-discoveries/' + op['id'] + '/import', json={'names': ['main-dingofs', 'test-dingofs']})
        assert response.status_code == 200, response.text
        rows = response.json()['created']
        assert [r['name'] for r in rows] == ['测试机器', '测试机器']
        url = '/api/v1/clusters/' + rows[0]['id']
        row = other.get(url).json()
        assert row['external_name'] == 'main-dingofs'
        body = {'base_revision': row['revision'], 'name': '自定义别名'}
        assert other.patch(url, json=body).status_code == 403
        result = owner.patch(url, json=body)
        assert result.status_code == 200, result.text
        assert result.json()['name'] == '自定义别名'
        assert result.json()['external_name'] == 'main-dingofs'
        result = admin.patch(url, json={'base_revision': result.json()['revision'], 'name': '管理员别名'})
        assert result.status_code == 200
        response = owner.post('/api/v1/cluster-discoveries/' + op['id'] + '/import', json={'names': ['main-dingofs']})
        assert response.json()['existing'][0]['name'] == '管理员别名'
