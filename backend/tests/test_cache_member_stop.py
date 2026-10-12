from types import SimpleNamespace as NS
import pytest
from dingofs_platform.resources import commands, service, remote_helper as helper
from dingofs_platform.errors import Problem


def test_stop_expands_members_across_creation_records_without_losing_ownership(monkeypatch):
    records = [NS(id='r1', name='g', data={'members': [{'member_id': 'a', 'machine_id': 'm1', 'target_user': 'root'}]}),
               NS(id='r2', name='g', data={'members': [{'member_id': 'b', 'machine_id': 'm2', 'target_user': 'jenkins'}, {'member_id': 'c', 'machine_id': 'm2', 'target_user': 'jenkins'}]})]
    db = NS(scalars=lambda query: records)
    monkeypatch.setattr(service, 'step', lambda db, actor, cluster, action, params, **kw: dict(action=action, parameters=params, **kw))
    params = commands.validate('cache.stop', {'member_ids': ['a', 'b']})
    work, resource = service.prepare(db, None, NS(id='cluster'), 'cache.stop', params)
    assert resource is None
    assert [w['record']['member_id'] for w in work] == ['a', 'b']
    assert [w['resource_id'] for w in work] == ['r1', 'r2']
    assert [w['action'] for w in work] == ['cache.stop', 'cache.stop']


def test_stop_rejects_unmanaged_member_before_any_remote_work(monkeypatch):
    monkeypatch.setattr(service, 'step', lambda *a, **kw: pytest.fail('must validate all targets first'))
    with pytest.raises(Problem) as exc:
        service.prepare(NS(scalars=lambda q: [], scalar=lambda q: None), None, NS(id='c'), 'cache.stop', {'member_ids': ['external']})
    assert exc.value.status == 422


@pytest.mark.parametrize('params', [{'member_ids': []}, {'member_ids': ['a', 'a']}, {'member_ids': ['a'], 'resource_id': 'r'}, {'member_ids': ['x']*101}])
def test_stop_rejects_invalid_targets(params):
    with pytest.raises(ValueError):
        commands.validate('cache.stop', params)


def test_waits_for_all_selected_members_to_be_offline(monkeypatch):
    states = iter([[{'member_id': 'a', 'state': 1}, {'member_id': 'other', 'state': 1}],
                   [{'member_id': 'a', 'state': 3}, {'member_id': 'other', 'state': 1}]])
    monkeypatch.setattr(helper, 'member_list', lambda req, **kw: next(states))
    monkeypatch.setattr(helper.time, 'sleep', lambda seconds: None)
    state, data = helper.wait_members_offline({'parameters': {'member_ids': ['a', 'absent']}})
    assert state == 'stopped'
    assert data['member_ids'] == ['a', 'absent']


def test_offline_wait_has_a_deadline_and_does_not_treat_unknown_as_offline(monkeypatch):
    monkeypatch.setattr(helper, 'member_list', lambda req, **kw: [{'member_id': 'a', 'state': 0}])
    clock = {"now": 0}
    monkeypatch.setattr(helper.time, "monotonic", lambda: clock["now"])
    monkeypatch.setattr(helper.time, "sleep", lambda seconds: clock.update(now=clock["now"]+seconds))
    with pytest.raises(ValueError, match='a'):
        helper.wait_members_offline({'parameters': {'member_ids': ['a']}})


def test_stop_keeps_group_registration_and_only_stops_owned_process(monkeypatch):
    from contextlib import contextmanager
    process={'pid':123}
    state={'process':process}
    @contextmanager
    def owned(*args, **kw):
        yield NS(load=lambda:state, save=lambda value:None)
    monkeypatch.setattr(helper,'OwnedState',owned)
    monkeypatch.setattr(helper,'process_identity',lambda pid:process)
    monkeypatch.setattr(helper,'same_process',lambda a,b:True)
    monkeypatch.setattr(helper,'_membership',lambda req:{'member_id':'a'})
    monkeypatch.setattr(helper,'_leave',lambda req:pytest.fail('stop must retain group membership'))
    stopped=[]
    monkeypatch.setattr(helper,'stop_recorded_process',lambda process:stopped.append(process))
    result=helper.lifecycle({'action':'cache.stop','resource_id':'r','record':{'member_id':'a','state_dir':'/tmp/r'}})
    assert result[0]=='stopped'
    assert stopped==[process]
