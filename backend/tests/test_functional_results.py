"""Pure child evaluation from frozen selection, events, and trusted transport facts."""
import socket
import subprocess

import pytest


@pytest.fixture(autouse=True)
def deny_external_io(monkeypatch):
    def denied(*_args, **_kwargs):
        raise AssertionError('external I/O is forbidden in pure result tests')

    monkeypatch.setattr(socket.socket, 'connect', denied)
    monkeypatch.setattr(socket, 'create_connection', denied)
    monkeypatch.setattr(subprocess, 'Popen', denied)


SNAPSHOT = {'parent_id': 'parent', 'child_id': 'child', 'module': 'quota',
            'cases': ['a.yaml', 'b.yaml'], 'launch_token': 'frozen-token'}


def event(seq, kind, *, case_path=None, attempt=None, data=None, stage='cases',
          parent_id='parent', child_id='child', module='quota'):
    return {'version': 2, 'seq': seq, 'time': '2026-11-10T00:00:00Z',
            'type': kind, 'stage': stage, 'parent_id': parent_id,
            'child_id': child_id, 'module': module, 'case_path': case_path,
            'attempt': attempt, 'data': data or {}}


def summary(*, status='completed', passed=2, failed=0, unexecuted=0,
            cleanup_status='cleaned', recovery_status='not_required',
            retained_resources=None, suite_errors=0, results=None,
            cancelled=False, execution_targets=None):
    return {'status': status, 'cancelled': cancelled, 'total': 2,
            'completed': 2 - unexecuted, 'unexecuted': unexecuted,
            'passed': passed, 'failed': failed, 'skipped': 0,
            'known_bugs': 0, 'suite_errors': suite_errors,
            'cleanup_status': cleanup_status, 'recovery_status': recovery_status,
            'retained_resources': retained_resources or [],
            'results': results or [{'case_path': 'a.yaml', 'attempt': 1, 'final': True,
                                    'status': 'PASS'},
                                   {'case_path': 'b.yaml', 'attempt': 1, 'final': True,
                                    'status': 'PASS'}],
            'execution_targets': execution_targets or [],
            'report_paths': {'allure_results': 'integration_123/quota/allure-results',
                             'events': 'functional-events.jsonl',
                             'resources': 'resources.jsonl'}}


def passing_events():
    return [event(1, 'attempt_finished', case_path='a.yaml', attempt=1,
                  data={'status': 'PASS'}),
            event(2, 'case_finished', case_path='a.yaml', attempt=1,
                  data={'status': 'PASS'}),
            event(3, 'attempt_finished', case_path='b.yaml', attempt=1,
                  data={'status': 'PASS'}),
            event(4, 'case_finished', case_path='b.yaml', attempt=1,
                  data={'status': 'PASS'}),
            event(5, 'suite_finished', stage='finished', data=summary())]


def ended(returncode=0):
    process = {'child_id': 'child', 'launch_token': 'frozen-token', 'pid': 81,
               'start_time': '2026-11-10T00:00:00Z', 'state': 'exited'}
    proof = {key: process[key] for key in ('child_id', 'launch_token', 'pid', 'start_time')}
    proof['returncode'] = returncode
    return {'process': process, 'returncode': returncode, 'end_proof': proof}


def evaluate(snapshot=None, events=None, remote_state=None):
    from dingofs_platform.functional.results import evaluate_child
    return evaluate_child(snapshot or SNAPSHOT, events if events is not None else passing_events(),
                          remote_state if remote_state is not None else ended())


def test_success_requires_exact_final_cases_and_verified_remote_end():
    result = evaluate()
    assert result.child_state == 'success'
    assert result.case_counts == {'passed': 2, 'failed': 0, 'skipped': 0,
                                  'known_bugs': 0, 'completed': 2, 'total': 2}
    assert result.end_proof is True
    assert result.may_continue is True
    assert result.missing == [] and result.not_run == []


@pytest.mark.parametrize('phase', ['intent', 'retained', 'unknown'])
def test_uncertain_preexisting_resource_blocks_success_and_continuation(phase):
    resource = dict(id='borrowed', kind='cache', cluster='cluster', host='host', user='test',
                    name='member', path=None, port=1234, owned=False, phase=phase,
                    remote_identity={'member_id': 'member'})
    events = [event(1, 'resource_changed', data={'resource': resource}), *passing_events()]
    for index, row in enumerate(events, 1): row['seq'] = index
    events[-1]['data']['retained_resources'] = [resource]
    result = evaluate(events=events)
    assert result.child_state == 'needs_attention'
    assert result.may_continue is False
    assert result.retained_resources == [resource]


def test_verified_active_preexisting_resource_may_remain_in_place():
    resource = dict(id='borrowed', kind='cache', cluster='cluster', host='host', user='test',
                    name='member', path=None, port=1234, owned=False, phase='active',
                    remote_identity={'member_id': 'member'})
    events = [event(1, 'resource_changed', data={'resource': resource}), *passing_events()]
    for index, row in enumerate(events, 1): row['seq'] = index
    result = evaluate(events=events)
    assert result.child_state == 'success' and result.may_continue
    assert result.retained_resources == []


def test_failed_then_passed_attempt_counts_one_final_case():
    events = [event(1, 'attempt_finished', case_path='a.yaml', attempt=1,
                    data={'status': 'FAIL'}),
              event(2, 'attempt_finished', case_path='a.yaml', attempt=2,
                    data={'status': 'PASS'}),
              event(3, 'case_finished', case_path='a.yaml', attempt=2,
                    data={'status': 'PASS'}),
              event(4, 'attempt_finished', case_path='b.yaml', attempt=1,
                    data={'status': 'PASS'}),
              event(5, 'case_finished', case_path='b.yaml', attempt=1,
                    data={'status': 'PASS'}),
              event(6, 'suite_finished', stage='finished', data=summary(
                  results=[{'case_path': 'a.yaml', 'attempt': 1, 'final': False,
                            'status': 'FAIL'},
                           {'case_path': 'a.yaml', 'attempt': 2, 'final': True,
                            'status': 'PASS'},
                           {'case_path': 'b.yaml', 'attempt': 1, 'final': True,
                            'status': 'PASS'}]))]
    result = evaluate(events=events)
    assert result.child_state == 'success'
    assert [item['status'] for item in result.attempt_records] == ['FAIL', 'PASS', 'PASS']
    assert result.case_counts['passed'] == 2


def test_not_run_is_not_reported_as_failed_case():
    events = [event(1, 'attempt_finished', case_path='a.yaml', attempt=1,
                    data={'status': 'FAIL'}),
              event(2, 'case_finished', case_path='a.yaml', attempt=1,
                    data={'status': 'FAIL'}),
              event(3, 'suite_finished', stage='finished', data=summary(
                  status='failed', passed=0, failed=1, unexecuted=1,
                  results=[{'case_path': 'a.yaml', 'attempt': 1, 'final': True,
                            'status': 'FAIL'}]))]
    result = evaluate(events=events, remote_state=ended(1))
    assert result.failed_cases == ['a.yaml']
    assert result.not_run == ['b.yaml']
    assert result.case_counts['failed'] == 1
    assert result.child_state == 'failed'
    assert result.may_continue is True


@pytest.mark.parametrize('changes', [
    {'status': 'failed', 'suite_errors': 1},
    {'cleanup_status': 'failed'},
    {'recovery_status': 'failed'},
])
def test_suite_and_finalizer_failures_prevent_success_even_if_cases_pass(changes):
    events = passing_events()
    events[-1] = event(5, 'suite_finished', stage='finished',
                       data=summary(**changes))
    result = evaluate(events=events)
    assert result.child_state != 'success'
    assert result.case_counts['passed'] == 2


def test_rc_zero_with_missing_final_case_is_not_success():
    events = [event(1, 'case_started', case_path='a.yaml'),
              event(2, 'attempt_finished', case_path='b.yaml', attempt=1,
                    data={'status': 'PASS'}),
              event(3, 'case_finished', case_path='b.yaml', attempt=1,
                    data={'status': 'PASS'}),
              event(4, 'suite_finished', stage='finished', data=summary(
                  passed=1, unexecuted=1,
                  results=[{'case_path': 'b.yaml', 'attempt': 1, 'final': True,
                            'status': 'PASS'}]))]
    result = evaluate(events=events)
    assert result.child_state != 'success'
    assert result.missing == ['a.yaml']
    assert result.not_run == []


def test_cancelled_suite_with_rc_zero_is_cancelled():
    events = passing_events()
    events[-1] = event(5, 'suite_finished', stage='finished',
                       data=summary(status='cancelled', cancelled=True))
    result = evaluate(events=events)
    assert result.child_state == 'cancelled'
    assert result.may_continue is False


def test_unverified_remote_end_is_unknown_and_retains_resources():
    resource = {'id': 'fs-1', 'kind': 'filesystem', 'cluster': 'cluster',
                'host': None, 'user': None, 'name': 'fs', 'path': None,
                'port': None, 'owned': True, 'phase': 'unknown',
                'remote_identity': {}}
    events = passing_events()
    events.insert(-1, event(5, 'resource_changed', stage='cleanup',
                            data={'resource': resource}))
    events[-1]['seq'] = 6
    remote = {'process': {**ended()['process'], 'state': 'unknown'},
              'returncode': 0}
    result = evaluate(events=events, remote_state=remote)
    assert result.child_state == 'unknown'
    assert result.may_continue is False
    assert result.end_proof is False
    assert result.retained_resources == [resource]


def test_failed_cleanup_blocks_next_child_even_when_no_resource_is_left():
    events = passing_events()
    events[-1] = event(5, 'suite_finished', stage='finished',
                       data=summary(cleanup_status='failed'))
    result = evaluate(events=events)
    assert result.child_state == 'failed'
    assert result.may_continue is False
    resource = {'id': 'fs-1', 'kind': 'filesystem', 'cluster': 'cluster',
                'host': None, 'user': None, 'name': 'fs', 'path': None,
                'port': None, 'owned': True, 'phase': 'retained',
                'remote_identity': {}}
    events[-1] = event(5, 'suite_finished', stage='finished', data=summary(
        cleanup_status='retained', retained_resources=[resource]))
    blocked = evaluate(events=events)
    assert blocked.child_state == 'needs_attention'
    assert blocked.may_continue is False


def test_unknown_cleanup_blocks_continuation_and_exit_code_alone_is_no_proof():
    events = passing_events()
    events[-1] = event(5, 'suite_finished', stage='finished',
                       data=summary(cleanup_status='unknown'))
    unresolved = evaluate(events=events)
    assert unresolved.child_state != 'success'
    assert unresolved.may_continue is False
    no_proof = evaluate(events=passing_events(), remote_state={
        'process': ended()['process'], 'returncode': 0})
    assert no_proof.end_proof is False
    assert no_proof.child_state != 'success'
    assert no_proof.may_continue is False


def test_report_failure_does_not_erase_case_results_and_absence_has_no_link():
    failed_report = evaluate(remote_state={**ended(), 'report_error': 'render failed'})
    assert failed_report.report_status == 'failed'
    assert failed_report.report_path is None
    assert failed_report.case_counts['passed'] == 2
    absent = evaluate()
    assert absent.report_status == 'missing'
    assert absent.report_path is None
    ready = evaluate(remote_state={**ended(), 'verified_report': {
        'child_id': 'child', 'html_path': 'integration_123/quota/report/index.html'}})
    assert ready.report_status == 'ready'
    assert ready.report_path == 'integration_123/quota/report/index.html'


def test_report_finished_failure_is_separate_from_successful_cases():
    events = passing_events() + [event(6, 'report_finished', stage='reporting', data={
        'success': False, 'path': 'integration_123/quota/report/index.html',
        'mode': 'allure'})]
    result = evaluate(events=events)
    assert result.child_state == 'success'
    assert result.case_counts['passed'] == 2
    assert result.report_status == 'failed'
    assert result.report_path is None


def test_verified_html_must_match_report_event_path():
    events = passing_events() + [event(6, 'report_finished', stage='reporting', data={
        'success': True, 'path': 'integration_123/quota/report/index.html',
        'mode': 'allure'})]
    result = evaluate(events=events, remote_state={**ended(), 'verified_report': {
        'child_id': 'child', 'html_path': 'another/report/index.html'}})
    assert result.report_status == 'failed'
    assert result.report_path is None


@pytest.mark.parametrize('mutation', [
    {'parent_id': 'other'}, {'child_id': 'other'}, {'module': 'other'},
    {'case_path': 'other.yaml'},
])
def test_event_identity_and_selected_paths_are_refused(mutation):
    from dingofs_platform.functional.results import ChildResultError
    events = passing_events()
    events[0] = {**events[0], **mutation}
    with pytest.raises(ChildResultError):
        evaluate(events=events)


def test_expected_execution_targets_are_frozen_and_checked():
    from dingofs_platform.functional.results import ChildResultError
    snapshot = {**SNAPSHOT, 'expected_targets': [{'source_host': 'host-1',
                 'machine_id': 'machine-1', 'machine_name': 'name-1',
                 'address': '10.0.0.1', 'port': 22, 'user': 'tester'}]}
    events = passing_events()
    with pytest.raises(ChildResultError):
        evaluate(snapshot=snapshot, events=events)


def test_suite_errors_block_continuation_even_when_cases_and_cleanup_pass():
    events = passing_events()
    events[-1] = event(5, 'suite_finished', stage='finished',
                       data=summary(status='failed', suite_errors=1))
    result = evaluate(events=events, remote_state=ended(1))
    assert result.child_state == 'failed'
    assert result.may_continue is False


def test_cancelled_event_blocks_success_despite_completed_summary_and_rc_zero():
    events = passing_events()
    events.insert(-1, event(5, 'cancelled', stage='cleanup'))
    events[-1]['seq'] = 6
    result = evaluate(events=events)
    assert result.child_state == 'cancelled'
    assert result.may_continue is False


def test_final_case_must_match_finished_attempt_status():
    from dingofs_platform.functional.results import ChildResultError
    events = passing_events()
    events[0]['data']['status'] = 'FAIL'
    with pytest.raises(ChildResultError):
        evaluate(events=events)


def test_final_case_requires_finished_attempt():
    from dingofs_platform.functional.results import ChildResultError
    events = passing_events()
    del events[0]
    for seq, item in enumerate(events, 1):
        item['seq'] = seq
    with pytest.raises(ChildResultError):
        evaluate(events=events)


def test_summary_must_include_every_nonfinal_attempt():
    events = [event(1, 'attempt_finished', case_path='a.yaml', attempt=1,
                    data={'status': 'FAIL'})] + passing_events()
    for seq, item in enumerate(events, 1):
        item['seq'] = seq
    events[1]['attempt'] = 2
    events[2]['attempt'] = 2
    events[-1]['data']['results'][0]['attempt'] = 2
    result = evaluate(events=events)
    assert result.child_state == 'needs_attention'
    assert result.may_continue is False


def test_summary_cannot_invent_an_extra_nonfinal_attempt():
    events = passing_events()
    events[-1]['data']['results'].append({'case_path': 'a.yaml',
                                           'attempt': 3, 'final': False,
                                           'status': 'FAIL'})
    result = evaluate(events=events)
    assert result.child_state == 'needs_attention'
    assert result.may_continue is False


def resource_record(**changes):
    resource = {'id': 'fs-1', 'kind': 'filesystem', 'cluster': 'cluster',
                'host': None, 'user': None, 'name': 'fs', 'path': None,
                'port': None, 'owned': True, 'phase': 'unknown',
                'remote_identity': {}}
    resource.update(changes)
    return resource


def test_summary_cannot_erase_owned_unknown_resource_without_removal_event():
    from dingofs_platform.functional.results import ChildResultError
    events = passing_events()
    events.insert(-1, event(5, 'resource_changed', stage='cleanup',
                            data={'resource': resource_record()}))
    events[-1]['seq'] = 6
    events[-1]['data']['retained_resources'] = [resource_record(
        owned=False, phase='removed')]
    with pytest.raises(ChildResultError):
        evaluate(events=events)


@pytest.mark.parametrize('bad', [
    resource_record(port=True),
    resource_record(remote_identity=[]),
    resource_record(kind=''),
])
def test_resource_record_types_are_validated(bad):
    from dingofs_platform.functional.results import ChildResultError
    events = passing_events()
    events.insert(-1, event(5, 'resource_changed', stage='cleanup',
                            data={'resource': bad}))
    events[-1]['seq'] = 6
    with pytest.raises(ChildResultError):
        evaluate(events=events)


def test_authoritative_resource_removal_event_allows_clean_completion():
    events = passing_events()
    events.insert(-1, event(5, 'resource_changed', stage='cleanup',
                            data={'resource': resource_record()}))
    events.insert(-1, event(6, 'resource_changed', stage='cleanup',
                            data={'resource': resource_record(phase='removed')}))
    events[-1]['seq'] = 7
    result = evaluate(events=events)
    assert result.child_state == 'success'
    assert result.retained_resources == []
    assert result.may_continue is True


def test_invalid_summary_resource_record_is_refused():
    from dingofs_platform.functional.results import ChildResultError
    events = passing_events()
    events[-1]['data']['retained_resources'] = [resource_record(port=True)]
    with pytest.raises(ChildResultError):
        evaluate(events=events)
