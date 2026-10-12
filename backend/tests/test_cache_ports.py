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
