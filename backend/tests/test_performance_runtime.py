"""A requested measurement duration must reach DTT, never become only a timeout."""
import pytest
import json
from pydantic import ValidationError

from dingofs_platform.performance.commands import argv_for
from dingofs_platform.performance.schemas import RunInput, TestSpec as BenchmarkSpec
from dingofs_platform.performance import remote_runner
from test_performance_runner import fixture_job


@pytest.mark.parametrize('tool', ['fio', 'elbencho'])
def test_runtime_is_forwarded_without_changing_dataset(tool):
    spec = BenchmarkSpec(tool=tool, total_size='1GiB', runtime_seconds=60)
    assert spec.total_size == '1073741824'
    assert spec.runtime_seconds == 60
    args = argv_for(spec, '/data', '/report', 'dtt')
    assert args[args.index('--runtime-seconds') + 1] == '60'
    assert '--duration' not in args


@pytest.mark.parametrize('value', [0, -1, 604801, 1.5, True, '60'])
def test_invalid_measurement_runtime_rejected(value):
    with pytest.raises(ValidationError):
        BenchmarkSpec(tool='fio', runtime_seconds=value)


def test_finite_jobs_do_not_request_runtime():
    spec = BenchmarkSpec(tool='fio')
    assert '--runtime-seconds' not in argv_for(spec, '/data', '/report', 'dtt')


def test_runtime_matrix_is_expanded_and_preserved():
    plan = RunInput(name='timed', machine_id='m', target_path='/data', tests=[
        {'tool': 'fio', 'runtime_seconds': [30, 60], 'total_size': '1GiB'},
    ])
    assert [s['parameters']['runtime_seconds'] for s in plan.scenarios] == [30, 60]


@pytest.mark.parametrize('runtime', [10, [10, 20]])
def test_mdtest_runtime_is_rejected_instead_of_silently_ignored(runtime):
    with pytest.raises(ValidationError, match='mdtest'):
        RunInput(name='metadata', machine_id='m', target_path='/data', tests=[
            {'tool': 'mdtest', 'runtime_seconds': runtime},
        ])


def test_timeout_must_cover_sequential_measurement_rounds():
    with pytest.raises(ValidationError, match='时长'):
        RunInput(name='timed', machine_id='m', target_path='/data', timeout_minutes=2,
                 tests=[{'tool': 'fio', 'runtime_seconds': 60, 'rounds': 2}])


@pytest.mark.parametrize('echoed', [None, 30, True])
def test_old_dtt_cannot_silently_run_a_finite_workload(tmp_path, monkeypatch, echoed):
    home, root, request = fixture_job(tmp_path, tools=('fio',))
    binary = home / '.local/share/dingofs-platform/tools/dtt/current/dtt'
    # A real subprocess boundary: an old wrapper accepts dry-run but ignores runtime.
    binary.write_text('#!/usr/bin/env python3\nimport json,sys\nfrom pathlib import Path\n'
                      'if "--dry-run" in sys.argv:\n print(json.dumps(' + repr({'runtime_seconds': echoed}) + '));sys.exit(0)\n'
                      '(Path.home()/"workload-started").touch()\n')
    spec = BenchmarkSpec(tool='fio', total_size='4KiB', concurrency=1, runtime_seconds=2)
    request['tests'] = [{'spec': spec.model_dump(), 'args': argv_for(spec, '__DATA__', '__OUTPUT__', 'dtt')[1:]}]
    (root / 'request.json').write_text(json.dumps(request))
    monkeypatch.setenv('HOME', str(home))
    remote_runner.execute(root)
    state = json.loads((root / 'state.json').read_text())
    assert state['state'] == 'failed'
    assert '升级' in state['error']
    assert not (home / 'workload-started').exists()


def test_timed_dtt_probe_validates_the_actual_echoed_plan(tmp_path):
    binary = tmp_path / 'dtt'
    binary.write_text('#!/usr/bin/env python3\nimport json,sys\n'
                      'assert "--dry-run" in sys.argv\n'
                      'print(json.dumps({"runtime_seconds":60,"tool":"fio"}))\n')
    binary.chmod(0o755)
    remote_runner.check_timed_dtt([str(binary), '--runtime-seconds', '60'], {'runtime_seconds': 60}, 5)


def write_timed_report(tmp_path, *, runtime=60, measured=60, io_bytes=104857600, rounds=None):
    folder = tmp_path / 'performance-fio-fixture'
    folder.mkdir()
    report = {
        'status': 'passed', 'plan': {'tool': 'fio', 'runtime_seconds': runtime, 'rounds': 1},
        'rounds': rounds if rounds is not None else [
            {'round': 1, 'status': 'passed', 'metrics': {'measurement_seconds': measured, 'io_bytes': io_bytes}},
        ],
        'statistics': {'complete': True, 'requested_rounds': 1, 'successful_rounds': 1, 'metrics': {}},
    }
    (folder / 'summary.json').write_text(json.dumps(report))


@pytest.mark.parametrize('changes', [
    {'runtime': None}, {'runtime': 30}, {'runtime': True}, {'measured': 1},
    {'measured': float('nan')}, {'io_bytes': 0}, {'io_bytes': True}, {'rounds': []},
    {'rounds': [{'round': 2, 'status': 'passed', 'metrics': {'measurement_seconds': 60, 'io_bytes': 10}}]},
])
def test_short_or_mismatched_timed_report_is_not_successful(tmp_path, changes):
    write_timed_report(tmp_path, **changes)
    with pytest.raises(ValueError, match='定时'):
        remote_runner.report_files(tmp_path, 'fio', expected={'tool': 'fio', 'runtime_seconds': 60, 'rounds': 1})


def test_timed_report_accepts_more_io_than_dataset(tmp_path):
    write_timed_report(tmp_path)
    summary, artifacts = remote_runner.report_files(tmp_path, 'fio', expected={
        'tool': 'fio', 'runtime_seconds': 60, 'rounds': 1, 'total_size': '4096',
    })
    assert summary['status'] == 'passed'
    assert summary['runtime_seconds'] == 60
    assert 'summary.json' in artifacts
