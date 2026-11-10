"""Execute the actual SSH RPC code locally; subprocess launch is always faked."""
import contextlib
import io
import json
import os
from pathlib import Path
import socket
import subprocess

import pytest

LOCAL_POPEN = subprocess.Popen

from dingofs_platform.functional import transport, remote_runner


@pytest.fixture(autouse=True)
def deny_network(monkeypatch):
    original_umask = os.umask(0o077)
    os.umask(original_umask)
    def deny(*args, **kwargs):
        raise AssertionError('network/process forbidden unless explicitly faked')
    monkeypatch.setattr(socket.socket, 'connect', deny)
    monkeypatch.setattr(subprocess, 'Popen', deny)
    yield
    os.umask(original_umask)


@pytest.fixture
def payload(tmp_path, monkeypatch):
    monkeypatch.setenv('HOME', str(tmp_path))
    return dict(version=2, parent_id='parent', child_id='child', launch_token='token', module='quota',
                env_name='env_original', cases=['a.yaml'], hashes={'a.yaml': 'b' * 64}, retries=0,
                immutable_path='/opt/dtt/pinned/dtt', runtime_manifest={'version': 2},
                context={'version': 1, 'parent_id': 'parent', 'child_id': 'child', 'module': 'quota',
                         'env_name': 'env_original', 'retries': 0, 'source_manifest': {},
                         'approved_targets': [], 'resolved_targets': [], 'functional_runtime': {'version': 2}})


def execute(code):
    stream = io.StringIO()
    with contextlib.redirect_stdout(stream):
        exec(compile(code, '<isolated-rpc>', 'exec'), {'__name__': 'rpc'})
    return json.loads(stream.getvalue())


def bootstrap(payload, monkeypatch):
    assert hasattr(transport, 'child_bootstrap_code'), 'guided bootstrap missing'
    launches = []
    class Process:
        pid = 123
        def __init__(self, argv, **kwargs): launches.append(argv)
    monkeypatch.setattr(subprocess, 'Popen', Process)
    result = execute(transport.child_bootstrap_code(payload))
    return Path(result['root']), launches


def test_duplicate_bootstrap_never_relaunches_and_output_stays_empty(payload, monkeypatch):
    root, launches = bootstrap(payload, monkeypatch)
    execute(transport.child_bootstrap_code(payload))
    assert len(launches) == 1
    assert (root / 'request.json').is_file()
    output = root.parent.parent / 'output' / 'parent' / 'child'
    assert not output.exists()
    with pytest.raises(ValueError):
        execute(transport.child_bootstrap_code({**payload, 'launch_token': 'different'}))
    assert len(launches) == 1


def test_bootstrap_crash_before_spawn_is_query_only(payload, monkeypatch):
    assert hasattr(transport, 'child_bootstrap_code'), 'guided bootstrap missing'
    def lost(*args, **kwargs): raise OSError('spawn result unknown')
    monkeypatch.setattr(subprocess, 'Popen', lost)
    with pytest.raises(OSError): execute(transport.child_bootstrap_code(payload))
    # A persisted request forbids another spawn even when pid is missing.
    result = execute(transport.child_bootstrap_code(payload))
    assert result['root']
    polled = execute(transport.child_snapshot_code(payload, {}))
    assert polled['state'] == 'unknown'


def test_remote_cursor_preserves_12000_events_partial_tail_and_duplicates(payload, monkeypatch):
    root, _ = bootstrap(payload, monkeypatch)
    output = root.parent.parent / 'output' / 'parent' / 'child'
    output.mkdir(parents=True)
    event = dict(version=2, time='2026-11-10T00:00:00Z', type='stage_started', stage='setup',
                 parent_id='parent', child_id='child', module='quota', case_path=None, attempt=None, data={})
    records = [{**event, 'seq': i} for i in range(1, 12001)]
    text = ''.join(json.dumps(row) + '\n' for row in records[:6000])
    text += json.dumps(records[5999]) + '\n'
    text += ''.join(json.dumps(row) + '\n' for row in records[6000:])
    complete_bytes = len(text.encode())
    path = output / 'functional-events.jsonl'
    path.write_text(text + '{"version":2')
    cursor, received = {}, []
    for _ in range(20):
        result = execute(transport.child_snapshot_code(payload, cursor))
        batch = result['event_batch']
        received += batch['events']
        cursor = {key: batch[key] for key in ('file_identity', 'last_event')}
        cursor['offset'] = batch['new_offset']
        if not result['has_more']: break
    assert [row['seq'] for row in received] == list(range(1, 12001))
    assert cursor['offset'] == complete_bytes
    assert batch['partial_tail'] is True
    assert execute(transport.child_snapshot_code(payload, cursor))['event_batch']['new_offset'] == complete_bytes
    path.rename(output / 'old-events')
    path.write_text(text)
    assert execute(transport.child_snapshot_code(payload, cursor))['protocol_error'] == 'file_identity_mismatch'


def test_supervisor_pins_single_module_context_and_proves_exact_end(payload, monkeypatch):
    root, _ = bootstrap(payload, monkeypatch)
    calls = []
    class Process:
        pid = 42
        returncode = 0
        def __init__(self, argv, **kwargs):
            calls.append(argv)
            output_root = Path(argv[argv.index('-o') + 1])
            assert not (output_root / 'parent' / 'child').exists()
        def poll(self): return 0
        def wait(self): return 0
    monkeypatch.setattr(subprocess, 'Popen', Process)
    monkeypatch.setattr(remote_runner, 'process_identity', lambda pid: '123456')
    remote_runner.run(root)
    argv = calls[0]
    assert argv[:7] == ['/opt/dtt/pinned/dtt', '-t', 'int', '-s', 'quota', '--env', 'env_original']
    assert '--functional-context' in argv and '--case-plan' in argv
    assert json.loads((root / 'context.json').read_text()) == payload['context']
    state = json.loads((root / 'state.json').read_text())
    assert state['process']['start_time'] == '123456'
    assert state['process']['state'] == 'exited'
    assert state['end_proof'] == dict(child_id='child', launch_token='token', pid=42,
                                     start_time='123456', returncode=0)


def test_cancel_is_forwarded_only_to_exact_child_output(payload, monkeypatch):
    root, _ = bootstrap(payload, monkeypatch)
    output = root.parent.parent / 'output' / 'parent' / 'child'
    output.mkdir(parents=True)
    (output / 'functional-events.jsonl').touch()
    execute(transport.child_snapshot_code(payload, {}, True))
    assert (output / 'functional-cancel').exists()
    assert not (output.parent / 'functional-cancel').exists()


def test_report_verified_inside_child_not_inferred_from_suite(payload, monkeypatch):
    root, _ = bootstrap(payload, monkeypatch)
    output = root.parent.parent / 'output' / 'parent' / 'child'
    output.mkdir(parents=True)
    state = {'state': 'exited', 'report_path': 'html/index.html'}
    (root / 'state.json').write_text(json.dumps(state))
    assert 'verified_report' not in execute(transport.child_snapshot_code(payload, {}))
    (output / 'html').mkdir()
    (output / 'html/index.html').write_text('<html>isolated</html>')
    assert execute(transport.child_snapshot_code(payload, {}))['verified_report'] == {
        'child_id': 'child', 'html_path': 'html/index.html'}
    (output / 'html/index.html').unlink()
    (output / 'html/index.html').symlink_to(root / 'request.json')
    assert 'verified_report' not in execute(transport.child_snapshot_code(payload, {}))


def test_supervisor_reentry_never_relaunches_even_after_clean_exit(payload, monkeypatch):
    root, _ = bootstrap(payload, monkeypatch)
    calls = []
    class Process:
        pid = 42
        def __init__(self, *args, **kwargs): calls.append(args)
        def poll(self): return 0
        def wait(self): return 0
    monkeypatch.setattr(subprocess, 'Popen', Process)
    monkeypatch.setattr(remote_runner, 'process_identity', lambda pid: '123456')
    remote_runner.run(root)
    remote_runner.run(root)
    assert len(calls) == 1


def test_independent_journal_detects_resource_without_matching_event(payload, monkeypatch):
    root, _ = bootstrap(payload, monkeypatch)
    class Process:
        pid = 42
        def __init__(self, *args, **kwargs):
            output = root.parent.parent / 'output' / 'parent' / 'child'
            output.mkdir(parents=True)
            (output / 'resources.jsonl').write_text(json.dumps({'id': 'retained', 'phase': 'retained'}) + '\n')
        def poll(self): return 0
        def wait(self): return 0
    monkeypatch.setattr(subprocess, 'Popen', Process)
    monkeypatch.setattr(remote_runner, 'process_identity', lambda pid: '123456')
    remote_runner.run(root)
    state = json.loads((root / 'state.json').read_text())
    assert state.get('journal_verified') is False
    assert state['protocol_error'] == 'resource_journal_mismatch'


def test_shipped_reader_runs_on_host_python_without_annotation_evaluation(payload, monkeypatch):
    root, _ = bootstrap(payload, monkeypatch)
    # This one local interpreter only imports the shipped stdlib reader; no
    # supervisor, Docker, workload, network or remote process is started.
    monkeypatch.setattr(subprocess, 'Popen', LOCAL_POPEN)
    result = subprocess.run(['/usr/bin/python3', '-I', '-B', '-c',
        'import sys;sys.path.insert(0,sys.argv[1]);import event_reader;print(event_reader.EventBatch.__name__)',
        str(root)], capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == 'EventBatch'
