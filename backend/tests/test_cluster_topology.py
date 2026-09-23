import pytest
from dingofs_platform.clusters.transport import ClusterCommand, build_command, ClusterCommandResult, ExecutionIdentity
from test_cluster_discovery import setup_machine, discover, transport


def test_topology_fixed_command():
    value = build_command(ClusterCommand('topology', 'jenkins', 'main-dingofs'), 'jenkins', 'nonce', False)
    assert 'export dingo_cluster=main-dingofs; dingo config show' in value
    assert 'cluster status' not in value


@pytest.mark.parametrize("failed", [False, True])
def test_topology_read_does_not_change_status(admin, app, failed):
    m = setup_machine(admin, app)
    app.state.cluster_transport = transport
    op = discover(admin, m)
    c = admin.post('/api/v1/cluster-discoveries/'+op['id']+'/import', json={'names':['main-dingofs']}).json()['created'][0]
    url = '/api/v1/clusters/'+c['id']
    before = admin.get(url).json()
    def read(config, cmd, **kw):
        assert cmd.kind == 'topology' and cmd.cluster_name == 'main-dingofs'
        return ClusterCommandResult(ExecutionIdentity(cmd.target_user, '/home/'+cmd.target_user, '/bin/dingo'), 'global:\n  user: jenkins\n', '', 1 if failed else 0)
    app.state.cluster_transport = read
    response = admin.post(url+'/topology', json={'base_revision':before['revision']})
    assert response.status_code == 202, response.text
    result = admin.get('/api/v1/cluster-operations/'+response.json()['id']).json()
    assert result['state'] == ('failed' if failed else 'succeeded'), result
    assert result['result']['stdout'] == 'global:\n  user: jenkins\n'
    after = admin.get(url).json()
    for field in ['status_snapshot','status_success_at','status_attempt_state','status_output']:
        assert after[field] == before[field]
