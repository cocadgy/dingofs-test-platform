import socket
import pytest
from dingofs_platform.resources import remote_helper as helper, commands


def request(mode='auto', port=21000):
    return {'record':{'member_id':'new','listen_ip':'127.0.0.1','listen_port':port,'port_mode':mode,'reserved_ports':[]},'mds_addr':'localhost:6900'}


def test_auto_skips_real_socket_and_mds_and_reserved_ports(monkeypatch):
    monkeypatch.setattr(helper,'member_list',lambda req:[{'member_id':'other','ip':'127.0.0.1','port':21001}])
    with socket.socket() as occupied:
        occupied.bind(('0.0.0.0',21000)); occupied.listen()
        req=request(); req['record']['reserved_ports']=[21002]
        assert helper.select_cache_port(req)==21003


def test_manual_conflict_reports_port_and_suggestion(monkeypatch):
    monkeypatch.setattr(helper,'member_list',lambda req:[])
    with socket.socket() as occupied:
        occupied.bind(('0.0.0.0',0)); occupied.listen()
        port=occupied.getsockname()[1]
        with pytest.raises(ValueError,match=str(port)) as error:
            helper.select_cache_port(request('manual',port))
        assert '建议' in str(error.value)


def test_auto_multiple_members_can_omit_unique_ports():
    member={'machine_id':'m','target_user':'jenkins','listen_ip':'127.0.0.1','cache_dir':'/tmp/cache','port_mode':'auto'}
    result=commands.validate('cache.plan',{'group_name':'g','members':[member,member]})
    assert len(result['members'])==2


def test_startup_rechecks_port_and_persists_it_before_launch(tmp_path, monkeypatch):
    req=request(); req.update(action='cache.create',resource_id='r')
    req['record'].update(state_dir=str(tmp_path/'state'),cache_dir=str(tmp_path/'cache'),log_dir=str(tmp_path/'logs'),group_name='g',cache_size_mb=1024,use_rdma=False)
    monkeypatch.setattr(helper,'select_cache_port',lambda req:21007)
    monkeypatch.setattr(helper,'find_process',lambda req:None)
    class Stopped:
        def poll(self): return 1
    captured=[]
    def launch(req,argv):
        with open(tmp_path/'state'/'state.json') as stream:
            state=__import__('json').load(stream)
        captured.append((argv,state))
        return Stopped()
    monkeypatch.setattr(helper,'_launch',launch)
    with pytest.raises(ValueError,match='launcher failed'):
        helper.lifecycle(req)
    assert '--listen_port=21007' in captured[0][0]
    assert captured[0][1]['listen_port']==21007


def test_member_identity_uses_persisted_port_on_recovery(tmp_path, monkeypatch):
    req=request(); req.update(action='cache.stop',resource_id='r')
    req['record'].update(state_dir=str(tmp_path/'state'),group_name='g')
    with helper.OwnedState(req['record']['state_dir'],'r:new',create=True) as store:
        store.save({'listen_port':21007,'launch_started':False})
    seen=[]
    monkeypatch.setattr(helper,'_membership',lambda req:seen.append(req['record']['listen_port']))
    state,_=helper.lifecycle(req)
    assert state=='stopped'
    assert seen==[21007]


def test_exhaustion_is_explicit_and_manual_never_silently_changes(monkeypatch):
    monkeypatch.setattr(helper,'member_list',lambda req:[])
    monkeypatch.setattr(helper,'port_busy',lambda port:True)
    with pytest.raises(ValueError,match='已无可用端口'):
        helper.select_cache_port(request())
    with pytest.raises(ValueError,match='21000'):
        helper.select_cache_port(request('manual'))


def test_port_probe_uses_wildcards_so_other_local_address_is_not_missed(monkeypatch):
    monkeypatch.setattr(helper,'member_list',lambda req:[])
    with socket.socket() as occupied:
        occupied.bind(('127.0.0.1',0)); occupied.listen()
        port=occupied.getsockname()[1]
        assert helper.port_busy(port)


@pytest.mark.parametrize('other,expected', [
    ({'member_id': 'external', 'listen_ip': '192.0.2.1', 'listen_port': 21000}, {21000}),
    ({'member_id': 'external', 'listen_ip': '192.0.2.2', 'listen_port': 21000}, {21000}),
    ({'member_id': 'external', 'listen_ip': '198.51.100.1', 'listen_port': 21000}, set()),
    ({'member_id': 'external', 'listen_ip': '192.0.2.1', 'listen_port': None}, set()),
    ({'member_id': 'external', 'listen_ip': '192.0.2.1', 'listen_port': True}, set()),
    ({'member_id': 'new', 'listen_ip': '192.0.2.1', 'listen_port': 21000}, set()),
])
def test_external_members_reserve_only_valid_ports_on_target_machine(admin, app, other, expected):
    from conftest import linked
    from dingofs_platform.inventory.models import Machine
    from dingofs_platform.resources.models import ManagedResource
    from dingofs_platform.resources.port_planning import reserved_ports
    m, cluster, _ = linked(admin)
    with app.state.session_factory.begin() as db:
        target = db.get(Machine, m['id'])
        target.address = '192.0.2.1'
        target.hardware_info = {'interfaces': [{'addresses': ['192.0.2.2/24']}]}
        db.add(ManagedResource(cluster_id=cluster['id'], creator_id=target.creator_id,
            kind='cache', name='external', state='running', data={'members': [other]}))
        db.flush()
        assert reserved_ports(db, {'machine_id': m['id'], 'member_id': 'new',
                                  'listen_ip': '192.0.2.1'}) == expected


@pytest.mark.parametrize('address', [None, 123, []])
def test_malformed_external_address_does_not_break_other_reservations(address):
    from types import SimpleNamespace
    from dingofs_platform.resources.port_planning import reserved_ports
    machine = SimpleNamespace(address='192.0.2.1', aliases=[], hardware_info={})
    members = [
        {'member_id': 'unmapped', 'listen_ip': address, 'listen_port': 21000},
        {'member_id': 'managed', 'machine_id': 'machine', 'listen_ip': address, 'listen_port': 21001},
    ]
    # Only the DB I/O is replaced; exercise the actual reservation algorithm.
    db = SimpleNamespace(get=lambda *args: machine, scalars=lambda *args: [
        SimpleNamespace(state='running', data={'members': members})])
    assert reserved_ports(db, {'machine_id': 'machine', 'member_id': 'new',
                              'listen_ip': '192.0.2.1'}) == {21001}
