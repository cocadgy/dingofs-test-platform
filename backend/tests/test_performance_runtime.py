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
    assert summary['statistics']['metrics']['measurement_seconds'] == {'mean': 60, 'samples': 1}
    assert summary['statistics']['metrics']['io_bytes'] == {'mean': 104857600, 'samples': 1}
    assert 'summary.json' in artifacts


@pytest.mark.parametrize('field,bad_value', [
    ('plan', [1]), ('plan', 'bad'),
    ('metrics', [1]), ('metrics', 'bad'),
    ('round', [1]), ('round', 'bad'),
])
def test_malformed_timed_report_is_a_value_error(tmp_path, field, bad_value):
    write_timed_report(tmp_path)
    path = tmp_path / 'performance-fio-fixture/summary.json'
    payload = json.loads(path.read_text())
    if field == 'plan':
        payload['plan'] = bad_value
    elif field == 'metrics':
        payload['rounds'][0]['metrics'] = bad_value
    else:
        payload['rounds'][0] = bad_value
    path.write_text(json.dumps(payload))
    with pytest.raises(ValueError, match='定时'):
        remote_runner.report_files(tmp_path, 'fio', expected={'tool': 'fio', 'runtime_seconds': 60, 'rounds': 1})


def test_timed_report_averages_verified_round_measurements(tmp_path):
    write_timed_report(tmp_path, rounds=[
        {'round': 1, 'status': 'passed', 'metrics': {'measurement_seconds': 60, 'io_bytes': 10}},
        {'round': 2, 'status': 'passed', 'metrics': {'measurement_seconds': 62, 'io_bytes': 30}},
    ])
    path = tmp_path / 'performance-fio-fixture/summary.json'
    payload = json.loads(path.read_text())
    payload['plan']['rounds'] = 2
    payload['statistics'].update(requested_rounds=2, successful_rounds=2)
    path.write_text(json.dumps(payload))
    summary, _ = remote_runner.report_files(tmp_path, 'fio', expected={'tool': 'fio', 'runtime_seconds': 60, 'rounds': 2})
    assert summary['statistics']['metrics']['measurement_seconds'] == {'mean': 61, 'samples': 2}
    assert summary['statistics']['metrics']['io_bytes'] == {'mean': 20, 'samples': 2}


def test_failed_timed_report_preserves_dtt_error(tmp_path):
    write_timed_report(tmp_path)
    path = tmp_path / 'performance-fio-fixture/summary.json'
    payload = json.loads(path.read_text())
    payload['status'] = 'failed'
    payload['error'] = 'fio disk full during preparation'
    payload['plan'] = [1]
    payload['statistics']['metrics'] = [1]
    path.write_text(json.dumps(payload))
    summary, _ = remote_runner.report_files(tmp_path, 'fio', expected={'tool': 'fio', 'runtime_seconds': 60, 'rounds': 1})
    assert summary['error'] == 'fio disk full during preparation'


def install_timed_dtt(binary, *, corrupt_first=False):
    binary.write_text('''#!/usr/bin/env python3
import json,sys
from pathlib import Path
a=sys.argv[1:]
get=lambda key:a[a.index(key)+1]
runtime=int(get('--runtime-seconds'))
tool=get('-t')
if '--dry-run' in a:
    print(json.dumps({'tool':tool,'runtime_seconds':runtime,'rounds':int(get('--rounds'))}))
    sys.exit(0)
output=Path(get('-o'))/('performance-'+tool+'-fixture')
output.mkdir(parents=True)
with (Path.home()/'timed-invocations').open('a') as stream:
    stream.write(Path(get('-m')).name+'\\n')
metrics={'measurement_seconds':runtime+1,'io_bytes':8192}
if CORRUPT_FIRST and 'scene-001' in get('-m'):
    metrics=[1]
report={'status':'passed','plan':{'tool':tool,'runtime_seconds':runtime,'rounds':1},
        'rounds':[{'round':1,'status':'passed','metrics':metrics}],
        'statistics':{'complete':True,'requested_rounds':1,'successful_rounds':1,
                      'metrics':{'bandwidth_mib_s':{'mean':3,'samples':1}}}}
(output/'summary.json').write_text(json.dumps(report))
(output/'index.html').write_text('<html>timed report</html>')
'''.replace('CORRUPT_FIRST', repr(corrupt_first)))
    binary.chmod(0o755)


def test_timed_pipeline_runs_dryrun_and_collects_measured_report(tmp_path, monkeypatch):
    home, root, request = fixture_job(tmp_path, tools=('fio',))
    install_timed_dtt(home / '.local/share/dingofs-platform/tools/dtt/current/dtt')
    spec = BenchmarkSpec(tool='fio', total_size='4KiB', concurrency=1, runtime_seconds=2)
    request['tests'] = [{'spec': spec.model_dump(), 'args': argv_for(spec, '__DATA__', '__OUTPUT__', 'dtt')[1:]}]
    (root / 'request.json').write_text(json.dumps(request))
    monkeypatch.setenv('HOME', str(home))
    remote_runner.execute(root)
    state = json.loads((root / 'state.json').read_text())
    reports = json.loads((root / 'reports.json').read_text())
    assert state['state'] == 'success'
    assert (home / 'timed-invocations').read_text() == 'fio\n'
    assert reports['fio']['state'] == 'success'
    assert reports['fio']['summary']['runtime_seconds'] == 2
    assert reports['fio']['summary']['statistics']['metrics']['measurement_seconds'] == {'mean': 3, 'samples': 1}
    assert reports['fio']['summary']['statistics']['metrics']['io_bytes'] == {'mean': 8192, 'samples': 1}
    assert 'summary.json' in reports['fio']['artifacts']
    assert 'index.html' in reports['fio']['artifacts']


def test_malformed_timed_scene_does_not_skip_later_matrix_scene(tmp_path, monkeypatch):
    home, root, request = fixture_job(tmp_path, tools=('fio', 'fio'))
    install_timed_dtt(home / '.local/share/dingofs-platform/tools/dtt/current/dtt', corrupt_first=True)
    spec = BenchmarkSpec(tool='fio', total_size='4KiB', concurrency=1, runtime_seconds=2)
    request['tests'] = [
        {'id': f'scene-{index:03d}', 'spec': spec.model_dump(),
         'args': argv_for(spec, '__DATA__', '__OUTPUT__', 'dtt')[1:]}
        for index in (1, 2)
    ]
    (root / 'request.json').write_text(json.dumps(request))
    monkeypatch.setenv('HOME', str(home))
    remote_runner.execute(root)
    state = json.loads((root / 'state.json').read_text())
    reports = json.loads((root / 'reports.json').read_text())
    assert state['state'] == 'failed'
    assert state['progress'] == 100
    assert (home / 'timed-invocations').read_text() == 'scene-001\nscene-002\n'
    assert reports['scene-001']['state'] == 'failed'
    assert '报告读取失败' in reports['scene-001']['error']
    assert reports['scene-002']['state'] == 'success'
