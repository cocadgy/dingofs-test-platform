"""Pure evaluation of one frozen functional module child.

``remote_state`` is trusted transport/supervisor data, never an HTTP body.
End proof requires a matching exited process identity, launch token, child ID,
and integer return code. Report readiness requires an independently verified
child-relative HTML artifact; the framework's Allure results path is not HTML.
"""

from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any


class ChildResultError(ValueError):
    """Event or frozen-selection mismatch that must block child completion."""


@dataclass(frozen=True)
class ChildResult:
    child_state: str
    stage: str
    case_counts: dict[str, int]
    case_results: list[dict[str, Any]]
    attempt_records: list[dict[str, Any]]
    failed_cases: list[str]
    missing: list[str]
    not_run: list[str]
    suite_errors: int
    cleanup_status: str
    recovery_status: str
    retained_resources: list[dict[str, Any]]
    report_status: str
    report_path: str | None
    may_continue: bool
    end_proof: bool
    termination_cause: str | None


_STATUSES = ('PASS', 'FAIL', 'SKIP', 'KNOWN_BUG')
_COUNTS = {'PASS': 'passed', 'FAIL': 'failed', 'SKIP': 'skipped',
           'KNOWN_BUG': 'known_bugs'}
_RESOURCE_PHASES = ('intent', 'active', 'retained', 'removed', 'unknown')


def _safe_relative(path: Any) -> bool:
    if not isinstance(path, str) or not path or '\\' in path:
        return False
    value = PurePosixPath(path)
    return (not value.is_absolute() and '..' not in value.parts
            and value.as_posix() == path and all(ord(c) >= 32 for c in path))


def _valid_resource(record: Any) -> bool:
    if not isinstance(record, dict):
        return False
    if any(not isinstance(record.get(key), str) or not record[key]
           for key in ('id', 'kind', 'cluster')):
        return False
    if any(record.get(key) is not None and not isinstance(record[key], str)
           for key in ('host', 'user', 'name', 'path')):
        return False
    port = record.get('port')
    return (all(key in record for key in ('host', 'user', 'name', 'path',
                                           'port', 'owned', 'phase', 'remote_identity'))
            and (port is None or type(port) is int and 1 <= port <= 65535)
            and type(record['owned']) is bool
            and record['phase'] in _RESOURCE_PHASES
            and isinstance(record['remote_identity'], dict))


def _resource_update(previous: dict | None, current: dict, *, summary: bool) -> None:
    if not _valid_resource(current):
        raise ChildResultError('invalid resource record')
    if previous and previous['owned'] != current['owned']:
        raise ChildResultError('resource ownership changed')
    if summary and previous and previous['phase'] != 'removed' and current['phase'] == 'removed':
        raise ChildResultError('summary cannot prove resource removal')


def _end_proof(snapshot: dict, state: dict) -> bool:
    process = state.get('process')
    proof = state.get('end_proof')
    rc = state.get('returncode')
    if (not isinstance(process, dict) or not isinstance(proof, dict)
            or process.get('state') != 'exited'
            or type(rc) is not int or type(proof.get('returncode')) is not int
            or proof['returncode'] != rc):
        return False
    if type(process.get('pid')) is not int or process['pid'] <= 0:
        return False
    for key in ('child_id', 'launch_token', 'pid', 'start_time'):
        if not process.get(key) or proof.get(key) != process[key]:
            return False
    return (process['child_id'] == snapshot['child_id']
            and (not snapshot.get('launch_token')
                 or process['launch_token'] == snapshot['launch_token']))


def _report(snapshot: dict, state: dict, ended: bool,
            report_event: dict | None) -> tuple[str, str | None]:
    if state.get('report_error'):
        return 'failed', None
    if report_event is not None:
        if (type(report_event.get('success')) is not bool
                or not _safe_relative(report_event.get('path'))):
            return 'failed', None
        if not report_event['success']:
            return 'failed', None
    artifact = state.get('verified_report')
    if artifact is not None:
        if (not isinstance(artifact, dict)
                or artifact.get('child_id') != snapshot['child_id']
                or not _safe_relative(artifact.get('html_path'))
                or (report_event is not None and
                    artifact['html_path'] != report_event['path'])):
            return 'failed', None
        return 'ready', artifact['html_path']
    return ('missing' if ended else 'pending'), None


def evaluate_child(snapshot: dict, events: list[dict], remote_state: dict) -> ChildResult:
    """Evaluate exact final cases and current resource/end facts.

    ``snapshot``: parent_id, child_id, module, cases (exact relative paths),
    optional launch_token and expected_targets. ``events`` is the persisted
    contiguous, deduplicated stream. ``remote_state`` holds process,
    returncode, end_proof, optional cancel_requested/timeout/protocol_error,
    and optional report_error/verified_report. A caller must supply only
    transport-verified supervisor facts in remote_state.
    """
    if not isinstance(snapshot, dict) or not isinstance(remote_state, dict):
        raise ChildResultError('snapshot and remote_state must be dictionaries')
    if any(not isinstance(snapshot.get(key), str) or not snapshot[key]
           for key in ('parent_id', 'child_id', 'module')):
        raise ChildResultError('missing frozen child identity')
    cases = snapshot.get('cases')
    if (not isinstance(cases, list) or not cases or
            any(not _safe_relative(path) for path in cases) or len(cases) != len(set(cases))):
        raise ChildResultError('invalid frozen case selection')
    if not isinstance(events, list):
        raise ChildResultError('events must be a list')
    expected = set(cases)
    started: set[str] = set()
    final: dict[str, dict[str, Any]] = {}
    attempts: list[dict[str, Any]] = []
    finished_attempts: dict[tuple[str, int], str] = {}
    resources: dict[str, dict[str, Any]] = {}
    suite: dict | None = None
    report_event: dict | None = None
    cancelled_event = False
    stage = 'waiting'
    previous_seq = 0
    for item in events:
        if not isinstance(item, dict):
            raise ChildResultError('invalid event')
        if (item.get('parent_id') != snapshot['parent_id']
                or item.get('child_id') != snapshot['child_id']
                or item.get('module') != snapshot['module']):
            raise ChildResultError('event child identity differs from frozen selection')
        seq = item.get('seq')
        if type(seq) is not int or seq != previous_seq + 1:
            raise ChildResultError('event sequence is not contiguous')
        previous_seq = seq
        path = item.get('case_path')
        if path is not None and path not in expected:
            raise ChildResultError('event case path differs from frozen selection')
        if not isinstance(item.get('data'), dict):
            raise ChildResultError('invalid event data')
        kind = item.get('type')
        stage = item.get('stage') or stage
        data = item['data']
        if path is not None and kind in ('case_started', 'attempt_started',
                                          'attempt_finished', 'case_finished'):
            started.add(path)
        if kind in ('attempt_started', 'attempt_finished', 'case_finished'):
            if path is None or type(item.get('attempt')) is not int or item['attempt'] <= 0:
                raise ChildResultError('case event lacks selected path or attempt')
        if kind == 'attempt_finished':
            if data.get('status') not in _STATUSES:
                raise ChildResultError('invalid attempt status')
            attempt_key = (path, item['attempt'])
            if attempt_key in finished_attempts or path in final:
                raise ChildResultError('duplicate or late finished attempt')
            finished_attempts[attempt_key] = data['status']
            attempts.append({'case_path': path, 'attempt': item['attempt'],
                             'status': data['status'], 'seq': seq})
        elif kind == 'case_finished':
            if data.get('status') not in _STATUSES or path in final:
                raise ChildResultError('invalid or duplicate final case')
            if finished_attempts.get((path, item['attempt'])) != data['status']:
                raise ChildResultError('final case differs from finished attempt')
            final[path] = {'case_path': path, 'attempt': item['attempt'],
                           'status': data['status']}
        elif kind == 'resource_changed':
            resource = data.get('resource')
            _resource_update(resources.get(resource.get('id')) if isinstance(resource, dict) else None,
                             resource, summary=False)
            resources[resource['id']] = resource
        elif kind == 'suite_finished':
            if suite is not None:
                raise ChildResultError('duplicate suite final event')
            suite = data
        elif kind == 'report_finished':
            if report_event is not None:
                raise ChildResultError('duplicate report final event')
            report_event = data
        elif kind == 'cancelled':
            cancelled_event = True
    missing = [path for path in cases if path in started and path not in final]
    not_run = [path for path in cases if path not in started and path not in final]
    counts = {name: 0 for name in _COUNTS.values()}
    for item in final.values():
        counts[_COUNTS[item['status']]] += 1
    counts['completed'] = len(final)
    counts['total'] = len(cases)
    suite_errors = 0
    cleanup = 'unknown'
    recovery = 'unknown'
    suite_status = None
    protocol_error = bool(remote_state.get('protocol_error'))
    if suite is not None:
        suite_status = suite.get('status')
        cleanup = suite.get('cleanup_status', 'unknown')
        recovery = suite.get('recovery_status', 'unknown')
        suite_errors = suite.get('suite_errors', 0)
        if (suite_status not in ('completed', 'failed', 'cancelled')
                or cleanup not in ('not_started', 'cleaned', 'retained', 'failed', 'unknown')
                or recovery not in ('not_required', 'recovered', 'failed', 'unknown')
                or type(suite_errors) is not int or suite_errors < 0):
            protocol_error = True
            suite_errors = 0 if type(suite_errors) is not int else max(0, suite_errors)
        for key, value in (('total', len(cases)), ('completed', len(final)),
                           ('unexecuted', len(cases) - len(final)),
                           ('passed', counts['passed']), ('failed', counts['failed']),
                           ('skipped', counts['skipped']),
                           ('known_bugs', counts['known_bugs'])):
            if type(suite.get(key)) is not int or suite[key] != value:
                protocol_error = True
        if snapshot.get('expected_targets') is not None and suite.get('execution_targets') != snapshot['expected_targets']:
            raise ChildResultError('execution targets differ from frozen selection')
        listed = suite.get('results')
        final_rows = []
        summary_attempts: dict[tuple[str, int], tuple[str, bool]] = {}
        if not isinstance(listed, list):
            protocol_error = True
        else:
            for row in listed:
                if (not isinstance(row, dict) or type(row.get('final')) is not bool
                        or row.get('case_path') not in expected
                        or type(row.get('attempt')) is not int or row['attempt'] <= 0
                        or row.get('status') not in _STATUSES):
                    protocol_error = True
                    continue
                key = (row['case_path'], row['attempt'])
                if key in summary_attempts or finished_attempts.get(key) != row['status']:
                    protocol_error = True
                summary_attempts[key] = (row['status'], row['final'])
                if row['final']:
                    final_rows.append(row)
            if (len(final_rows) != len(final) or
                    {row['case_path']: (row['attempt'], row['status']) for row in final_rows} !=
                    {path: (item['attempt'], item['status']) for path, item in final.items()}):
                protocol_error = True
            if set(summary_attempts) != set(finished_attempts):
                protocol_error = True
        retained = suite.get('retained_resources')
        if not isinstance(retained, list):
            protocol_error = True
        else:
            for resource in retained:
                _resource_update(resources.get(resource.get('id')) if isinstance(resource, dict) else None,
                                 resource, summary=True)
                resources[resource['id']] = resource
    retained_resources = [item for item in resources.values()
                          if (item.get('owned') is True and item.get('phase') != 'removed')
                          or item.get('phase') in ('intent', 'retained', 'unknown')]
    ended = _end_proof(snapshot, remote_state)
    report_status, report_path = _report(snapshot, remote_state, ended, report_event)
    cancelled = (cancelled_event or suite_status == 'cancelled'
                 or bool(suite and suite.get('cancelled'))
                 or bool(remote_state.get('cancelled'))
                 or bool(remote_state.get('cancel_requested'))
                 or bool(remote_state.get('timeout')))
    safe_resources = not retained_resources
    safe_recovery = recovery in ('not_required', 'recovered')
    ordinary_failure = (suite_status == 'failed' and counts['failed'] > 0
                        and remote_state.get('returncode') == 1 and not suite_errors)
    complete_success = (suite_status == 'completed' and remote_state.get('returncode') == 0
                        and not counts['failed'] and not missing and not not_run and not suite_errors)
    may_continue = (ended and suite is not None and safe_resources
                    and safe_recovery and cleanup == 'cleaned'
                    and not cancelled and not protocol_error
                    and (ordinary_failure or complete_success))
    if not ended:
        process = remote_state.get('process') or {}
        if process.get('state') == 'unknown':
            child_state = 'unknown'
        elif remote_state.get('cancel_requested') or remote_state.get('timeout'):
            child_state = 'cancelling'
        else:
            child_state = 'running' if process else 'queued'
    elif retained_resources or recovery == 'failed' or protocol_error or suite is None:
        child_state = 'needs_attention'
    elif cancelled:
        child_state = 'cancelled'
    elif (suite_status == 'completed' and remote_state['returncode'] == 0
          and not missing and not not_run and not counts['failed']
          and not suite_errors and cleanup == 'cleaned' and safe_recovery):
        child_state = 'success'
    else:
        child_state = 'failed'
    return ChildResult(child_state, stage, counts, list(final.values()), attempts,
                       [path for path in cases if final.get(path, {}).get('status') == 'FAIL'],
                       missing, not_run, suite_errors, cleanup, recovery,
                       retained_resources, report_status, report_path,
                       may_continue, ended,
                       'timeout' if remote_state.get('timeout') else
                       remote_state.get('termination_cause') or ('manual' if cancelled else None))
