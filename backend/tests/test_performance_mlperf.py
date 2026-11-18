"""MLPerf uses native training rounds, not fio runtime or exit-code-only success."""
import copy
import json

import pytest
from pydantic import ValidationError

from dingofs_platform.performance import remote_runner
from dingofs_platform.performance.commands import argv_for
from dingofs_platform.performance.schemas import RunInput, TestSpec as BenchmarkSpec
from test_performance_api import setup
from test_performance_runner import fixture_job


def test_mlperf_byte_budget_rounds_to_complete_native_model_files():
    spec = BenchmarkSpec(tool='mlperf', total_size='1GiB')
    assert (spec.file_count, spec.file_size, spec.total_size) == (8, '143439748', '1147517984')
    assert spec.runtime_seconds is None
    assert not spec.direct and spec.rw == 'read'
    assert BenchmarkSpec(**spec.model_dump()) == spec
    args = argv_for(spec, '/data', '/report', 'dtt')
    assert args == ['dtt', '-t', 'mlperf', '-s', 'benchmark', '-m', '/data', '-o', '/report',
                    '--mlperf-model', 'resnet50', '--mlperf-epochs', '5', '--mlperf-accelerators', '1',
                    '--concurrency', '4', '--file-count', '8', '--rounds', '1']


def test_mlperf_small_dataset_still_has_a_batch_per_accelerator():
    spec = BenchmarkSpec(tool='mlperf', mlperf_model='unet3d', total_size='1MiB', mlperf_accelerators=2)
    assert (spec.file_count, spec.total_size) == (14, '2052408792')


@pytest.mark.parametrize('parameters', [
    {'runtime_seconds': 60}, {'mlperf_model': 'unknown'}, {'mlperf_epochs': 0},
    {'mlperf_epochs': True}, {'mlperf_accelerators': '2'}, {'file_count': 0},
    {'file_count': 8, 'mlperf_accelerators': 3}, {'mlperf_model': 'unet3d', 'file_count': 6},
])
def test_mlperf_rejects_unsupported_or_impossible_native_parameters(parameters):
    with pytest.raises(ValidationError):
        BenchmarkSpec(tool='mlperf', **parameters)


def test_mlperf_matrix_expands_only_training_axes():
    request = RunInput(name='MLPerf', machine_id='m', target_path='/data', tests=[
        {'tool': 'mlperf', 'mlperf_model': ['resnet50', 'cosmoflow'], 'mlperf_epochs': [1, 2],
         'total_size': '1GiB'}, {'tool': 'fio', 'runtime_seconds': 30},
    ])
    assert len(request.scenarios) == 5
    assert [(s['parameters']['mlperf_model'], s['parameters']['mlperf_epochs'])
            for s in request.scenarios[:4]] == [('resnet50', 1), ('resnet50', 2), ('cosmoflow', 1), ('cosmoflow', 2)]
    assert request.scenarios[-1]['parameters']['runtime_seconds'] == 30


@pytest.mark.parametrize('axis', ['mlperf_model', 'mlperf_epochs', 'mlperf_accelerators',
                                  'concurrency', 'total_size', 'file_count', 'rounds'])
def test_mlperf_matrix_rejects_empty_training_axes(axis):
    with pytest.raises(ValidationError, match='每个参数至少选择一个值'):
        RunInput(name='MLPerf', machine_id='m', target_path='/data',
                 tests=[{'tool': 'mlperf', axis: []}])


def test_mlperf_options_preview_and_rerun_preserve_training_contract(admin):
    payload = setup(admin)
    payload['tests'] = [{'tool': 'mlperf', 'total_size': '1GiB', 'mlperf_epochs': 2, 'rounds': 2}]
    assert 'mlperf' in admin.get('/api/v1/performance/options').json()['tools']
    response = admin.post('/api/v1/performance/preview', json=payload)
    assert response.status_code == 200, response.text
    assert response.json()['total_bytes'] == 1147517984
    assert '--mlperf-epochs 2' in response.json()['tests'][0]['command']
    assert '--runtime-seconds' not in response.json()['tests'][0]['command']
    row = admin.post('/api/v1/performance/runs', json=payload)
    assert row.status_code == 202, row.text
    identifier = row.json()['id']
    assert admin.post('/api/v1/performance/runs/' + identifier + '/cancel').status_code == 200
    admin.app.state.performance_manager.process(identifier)
    again = admin.post('/api/v1/performance/runs/' + identifier + '/rerun')
    assert again.status_code == 202, again.text
    assert again.json()['snapshot']['tests'][0]['mlperf_epochs'] == 2
    assert again.json()['snapshot']['tests'][0]['file_count'] == 8


def native_report():
    plan = {'tool': 'mlperf', 'format': 'dtt-mlperf-v1', 'mlperf_model': 'resnet50',
            'mlperf_epochs': 5, 'mlperf_accelerators': 1, 'concurrency': 4,
            'file_count': 8, 'file_size': '143439748', 'total_size': '1147517984', 'rounds': 2}
    return {'format': 'dtt-mlperf-v1', 'plan': plan, 'status': 'passed', 'rounds': [
        {'round': i, 'status': 'passed', 'native_reports': [f'round-{i}-native-summary.json'],
         'metrics': {'samples_per_second': 100.0 * i, 'accelerator_utilization_percent': 40.0 * i}}
        for i in (1, 2)], 'statistics': {'complete': True, 'requested_rounds': 2, 'successful_rounds': 2, 'metrics': {}}}


def write_report(tmp_path, report):
    directory = tmp_path / 'performance-mlperf-current'
    directory.mkdir()
    for i in (1, 2):
        (directory / f'round-{i}-native-summary.json').write_text('{"epochs":5}')
    (directory / 'summary.json').write_text(json.dumps(report))


def test_mlperf_report_keeps_native_metrics_without_fabricated_fio_measurement(tmp_path):
    report = native_report()
    write_report(tmp_path, report)
    summary, artifacts = remote_runner.report_files(tmp_path, 'mlperf', expected=report['plan'])
    assert summary['status'] == 'passed'
    assert summary['statistics']['metrics']['samples_per_second'] == {'mean': 150.0, 'samples': 2}
    assert summary['statistics']['metrics']['accelerator_utilization_percent']['mean'] == 60.0
    assert 'iops' not in summary['statistics']['metrics']
    assert 'measurement_seconds' not in summary['statistics']['metrics']
    assert 'round-1-native-summary.json' in artifacts


@pytest.mark.parametrize('change', ['model', 'duplicate', 'missing', 'nan', 'bool', 'au', 'shape', 'evidence'])
def test_mlperf_false_success_or_corrupt_report_is_rejected(tmp_path, change):
    report = native_report()
    expected = copy.deepcopy(report['plan'])
    if change == 'model': report['plan']['mlperf_model'] = 'unet3d'
    if change == 'duplicate': report['rounds'][1]['round'] = 1
    if change == 'missing': report['rounds'].pop()
    if change == 'nan': report['rounds'][0]['metrics']['samples_per_second'] = float('nan')
    if change == 'bool': report['rounds'][0]['metrics']['samples_per_second'] = True
    if change == 'au': report['rounds'][0]['metrics']['accelerator_utilization_percent'] = 101
    if change == 'shape': report['rounds'][0]['metrics'] = [1]
    if change == 'evidence': report['rounds'][0]['native_reports'] = []
    write_report(tmp_path, report)
    with pytest.raises(ValueError, match='MLPerf'):
        remote_runner.report_files(tmp_path, 'mlperf', expected=expected)


def test_mlperf_contract_probe_rejects_old_dtt_before_workload(tmp_path, monkeypatch):
    home, root, request = fixture_job(tmp_path, tools=('fio',))
    binary = home / '.local/share/dingofs-platform/tools/dtt/current/dtt'
    binary.write_text('#!/usr/bin/env python3\nimport sys\nfrom pathlib import Path\n'
                      'if "--dry-run" in sys.argv: print("{}");sys.exit(0)\n'
                      '(Path.home()/"workload-started").touch()\n')
    spec = native_report()['plan']
    spec.pop('format')
    spec['runtime_seconds'] = None
    request['tests'] = [{'spec': spec, 'args': ['-t', 'mlperf', '-s', 'benchmark']}]
    (root / 'request.json').write_text(json.dumps(request))
    monkeypatch.setenv('HOME', str(home))
    remote_runner.execute(root)
    state = json.loads((root / 'state.json').read_text())
    assert state['state'] == 'failed'
    assert '升级' in state['error']
    assert not (home / 'workload-started').exists()


def test_mlperf_probe_validates_echoed_training_parameters(tmp_path):
    plan = native_report()['plan']
    binary = tmp_path / 'dtt'
    binary.write_text('#!/usr/bin/env python3\nimport json\nprint(json.dumps(' + repr(plan) + '))\n')
    binary.chmod(0o755)
    remote_runner.check_timed_dtt([str(binary)], plan, 5)
    plan['mlperf_epochs'] = 6
    with pytest.raises(RuntimeError, match='升级'):
        remote_runner.check_timed_dtt([str(binary)], plan, 5)
