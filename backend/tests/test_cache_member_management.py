import pytest
from dingofs_platform.resources import commands, remote_helper as h

@pytest.mark.parametrize('action,verb',[('cache.leave','leave'),('cache.unlock','unlock'),('cache.weight','set')])
def test_member_action_uses_live_endpoint_and_expected_group(monkeypatch,action,verb):
    p={'member_id':'m','group_name':'g'}
    if action=='cache.weight': p['weight']=123
    commands.validate(action,p)
    monkeypatch.setattr(h,'member_list',lambda req:[{'member_id':'m','group_name':'g','ip':'192.0.2.1','port':21000}])
    calls=[]
    monkeypatch.setattr(h,'run_command',lambda argv,**kw:calls.append(argv) or {'result':{}})
    state,data=h.manage_member({'action':action,'parameters':p,'mds_addr':'mds:6900'})
    assert state=='succeeded'
    assert calls[0][:4]==['dingo','cache','member',verb]
    assert calls[0][calls[0].index('--ip')+1]=='192.0.2.1'
    assert data['member_id']=='m'
    if verb=='set': assert calls[0][calls[0].index('--weight')+1]=='123'
    else: assert '--noconfirm' in calls[0]

def test_changed_group_does_not_receive_mutation(monkeypatch):
    monkeypatch.setattr(h,'member_list',lambda req:[{'member_id':'m','group_name':'new','ip':'192.0.2.1','port':21000}])
    monkeypatch.setattr(h,'run_command',lambda *a,**kw:pytest.fail('must not mutate'))
    with pytest.raises(ValueError):
        h.manage_member({'action':'cache.leave','parameters':{'member_id':'m','group_name':'old'}})

@pytest.mark.parametrize('weight',[-1,2**32,True,1.5])
def test_weight_rejects_invalid_uint32(weight):
    with pytest.raises(ValueError): commands.validate('cache.weight',{'member_id':'m','group_name':'','weight':weight})


def test_actions_use_management_entry_without_managed_process(monkeypatch):
    from types import SimpleNamespace
    from dingofs_platform.resources import service
    monkeypatch.setattr(service,'step',lambda db,actor,c,action,p:dict(action=action,parameters=p))
    for action in ('cache.leave','cache.unlock','cache.weight'):
        work,resource=service.prepare(None,None,SimpleNamespace(),action,{'member_id':'m','group_name':'g'})
        assert work[0]['action']==action and resource is None
