from types import SimpleNamespace as NS
import pytest
from dingofs_platform.resources import remote_helper as helper


@pytest.fixture(autouse=True)
def mocked_host_identity(monkeypatch):
    monkeypatch.setattr(helper, 'verify_cache_host', lambda address: None)


def request():
    return {'action':'cache.stop_external','mds_addr':'mds-a:6900,mds-b:6900',
            'parameters':{'member_id':'external'},
            'record':{'member_id':'external','group_name':'g','listen_ip':'192.0.2.1','listen_port':21000}}


def process(**flags):
    values=dict(id='external',group_name='g',listen_ip='192.0.2.1',listen_port='21000',mds_addrs='mds-b:6900,mds-a:6900')
    values.update(flags)
    return {'pid':321,'start_ticks':'20','exe':'/opt/dingo-cache','argv':['dingo-cache',*[f'--{k}={v}' for k,v in values.items()]]}


def test_external_stop_identifies_only_exact_member_and_reuses_pidfd_stop(monkeypatch):
    wanted=process();other=process(id='other')
    monkeypatch.setattr(helper.os,'geteuid',lambda:0)
    monkeypatch.setattr(helper.os,'scandir',lambda path:[NS(name='321'),NS(name='322')])
    monkeypatch.setattr(helper,'process_identity',lambda pid:wanted if pid==321 else other)
    stopped=[]
    monkeypatch.setattr(helper,'stop_recorded_process',lambda p:stopped.append(p))
    state,data=helper.stop_external_member(request())
    assert state=='stopped' and data['member_id']=='external'
    assert stopped==[wanted]


@pytest.mark.parametrize('flags',[{'group_name':'other'},{'listen_port':'21001'},{'listen_ip':'192.0.2.2'},{'mds_addrs':'other:6900'}])
def test_external_stop_rejects_same_uuid_with_different_identity(monkeypatch,flags):
    monkeypatch.setattr(helper.os,'geteuid',lambda:0)
    monkeypatch.setattr(helper.os,'scandir',lambda path:[NS(name='321')])
    monkeypatch.setattr(helper,'process_identity',lambda pid:process(**flags))
    monkeypatch.setattr(helper,'stop_recorded_process',lambda p:pytest.fail('must not signal'))
    with pytest.raises(ValueError):helper.stop_external_member(request())


def test_duplicate_processes_are_never_signalled(monkeypatch):
    monkeypatch.setattr(helper.os,'geteuid',lambda:0)
    monkeypatch.setattr(helper.os,'scandir',lambda path:[NS(name='321'),NS(name='322')])
    monkeypatch.setattr(helper,'process_identity',lambda pid:{**process(),'pid':pid})
    monkeypatch.setattr(helper,'stop_recorded_process',lambda p:pytest.fail('must not signal'))
    with pytest.raises(ValueError):helper.stop_external_member(request())


def test_external_stop_requires_privilege_for_complete_process_visibility(monkeypatch):
    monkeypatch.setattr(helper.os,'geteuid',lambda:1000)
    with pytest.raises(ValueError,match='root'):helper.stop_external_member(request())


def test_fresh_registration_check_rejects_changed_target(monkeypatch):
    req=request();req['record']={'members':[req['record']]}
    monkeypatch.setattr(helper,'member_list',lambda req:[{'member_id':'external','group_name':'g','ip':'192.0.2.9','port':21000}])
    with pytest.raises(ValueError):helper.verify_external_members(req)


def test_external_process_transport_does_not_require_dingo_in_root_path():
    from dingofs_platform.clusters.transport import ClusterCommand, build_command
    command=ClusterCommand('resource','root','cluster',resource_script='python3 -c pass',resource_requires_dingo=False)
    script=build_command(command,'jenkins','test',False)
    assert 'command -v python3' in script
    assert 'command -v dingo' not in script
    assert 'sudo' in script


def test_mapping_uses_interface_addresses_and_never_guesses_ambiguous_hosts():
    from dingofs_platform.resources import external_cache
    actor=NS(id='u',role='admin',disabled=False)
    cluster=NS(id='c')
    row={'member_id':'external','group_name':'g','ip':'192.0.2.1','port':21000}
    op=NS(state='succeeded',result={'steps':[{'data':{'members':{'result':{'members':[row]}}}}]})
    def machine(mid):
        return NS(id=mid,name=mid,address='ssh-'+mid,aliases=[],hardware_info={'interfaces':[{'addresses':['192.0.2.1/24']}]},ssh_password_ciphertext='encrypted')
    machines=[machine('m1')]
    db=NS(scalar=lambda q:op,scalars=lambda q:machines)
    assert external_cache.targets(db,actor,cluster)['external']['can_stop']
    machines.append(machine('m2'))
    target=external_cache.targets(db,actor,cluster)['external']
    assert not target['can_stop'] and '多台' in target['reason']
    machines.clear()
    target=external_cache.targets(db,actor,cluster)['external']
    assert not target['can_stop'] and '未找到' in target['reason']


def test_mapping_requires_machine_permission_not_just_cluster_permission():
    from dingofs_platform.resources import external_cache
    actor=NS(id='u',role='member',disabled=False)
    cluster=NS(id='c',creator_id='u')
    machine=NS(id='m',creator_id='other',name='m',address='192.0.2.1',aliases=[],hardware_info=None,ssh_password_ciphertext='encrypted')
    op=NS(state='succeeded',result={'steps':[{'data':{'members':{'result':{'members':[{'member_id':'x','ip':'192.0.2.1','port':21000}]}}}}]})
    target=external_cache.targets(NS(scalar=lambda q:op,scalars=lambda q:[machine]),actor,cluster)['x']
    assert not target['can_stop'] and '权限' in target['reason']


def test_external_missing_process_with_occupied_port_does_not_signal_other_process(monkeypatch):
    monkeypatch.setattr(helper.os,'geteuid',lambda:0)
    monkeypatch.setattr(helper.os,'scandir',lambda path:[])
    monkeypatch.setattr(helper,'port_busy',lambda port:True)
    monkeypatch.setattr(helper,'stop_recorded_process',lambda p:pytest.fail('must not signal by port alone'))
    with pytest.raises(ValueError,match='端口'):helper.stop_external_member(request())


def test_stale_host_mapping_fails_before_scanning_or_signalling(monkeypatch):
    monkeypatch.setattr(helper.os,'geteuid',lambda:0)
    def reject(address):raise ValueError('wrong host')
    monkeypatch.setattr(helper,'verify_cache_host',reject)
    monkeypatch.setattr(helper.os,'scandir',lambda path:pytest.fail('must not inspect wrong host processes'))
    with pytest.raises(ValueError,match='wrong host'):helper.stop_external_member(request())


def test_internal_stop_action_cannot_be_submitted_publicly():
    from dingofs_platform.resources import commands
    with pytest.raises(ValueError):commands.validate('cache.stop_external',{'member_id':'x'})
    with pytest.raises(ValueError):commands.validate('cache.stop',{'member_ids':['x'],'pid':123})


def test_external_stop_accepts_current_mds_subset_of_startup_addresses(monkeypatch):
    wanted=process(mds_addrs='mds-a:6900,mds-b:6900,mds-retired:6900')
    monkeypatch.setattr(helper.os,'geteuid',lambda:0)
    monkeypatch.setattr(helper.os,'scandir',lambda path:[NS(name='321')])
    monkeypatch.setattr(helper,'process_identity',lambda pid:wanted)
    stopped=[]
    monkeypatch.setattr(helper,'stop_recorded_process',lambda p:stopped.append(p))
    state,data=helper.stop_external_member(request())
    assert state=='stopped' and data['process_stopped'] is True
    assert stopped==[wanted]


@pytest.mark.parametrize('mds', ['mds-a:6900,foreign:6900', '', 'foreign:6900'])
def test_external_stop_rejects_incomplete_current_mds_identity(monkeypatch,mds):
    monkeypatch.setattr(helper.os,'geteuid',lambda:0)
    monkeypatch.setattr(helper.os,'scandir',lambda path:[NS(name='321')])
    monkeypatch.setattr(helper,'process_identity',lambda pid:process(mds_addrs=mds))
    monkeypatch.setattr(helper,'stop_recorded_process',lambda p:pytest.fail('must not signal'))
    with pytest.raises(ValueError):
        helper.stop_external_member(request())
