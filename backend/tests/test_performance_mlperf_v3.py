import pytest
from dingofs_platform.performance.schemas import TestSpec as Spec, ParameterMatrix
from dingofs_platform.performance.commands import argv_for
from dingofs_platform.performance.remote_runner import mlperf_summary, mlperf_plan_matches
from test_performance_api import setup


def test_legacy_training_default():
    spec = Spec(tool='mlperf', file_count=4)
    assert spec.mlperf_scenario == 'training'


def test_checkpoint_custom_plan_and_command():
    spec = Spec(tool='mlperf', mlperf_scenario='checkpointing', mlperf_model='custom',
                checkpoint_mode='read', checkpoint_count=2, checkpoint_size='16MiB')
    assert spec.total_size == str(32 * 1024**2)
    argv = argv_for(spec, '/data', '/output', 'dtt')
    assert argv[argv.index('--checkpoint-size') + 1] == str(16 * 1024**2)
    assert '--mlperf-epochs' not in argv


def test_kvcache_plan_duration_and_capacity():
    spec = Spec(tool='mlperf', mlperf_scenario='kvcache', mlperf_model='tiny-1b',
                runtime_seconds=5, total_size='1GiB', cpu_memory_gib=0)
    argv = argv_for(spec, '/data', '/output', 'dtt')
    assert argv[argv.index('--runtime-seconds') + 1] == '5'
    assert argv[argv.index('--total-size') + 1] == str(1024**3)
    assert '--file-count' not in argv


@pytest.mark.parametrize('kwargs', [
    {'mlperf_scenario': 'kvcache', 'mlperf_model': 'resnet50'},
    {'mlperf_scenario': 'checkpointing', 'mlperf_model': 'custom', 'runtime_seconds': 10},
    {'mlperf_scenario': 'kvcache', 'mlperf_model': 'tiny-1b', 'cpu_memory_gib': float('nan')},
])
def test_reject_wrong_scene_fields(kwargs):
    with pytest.raises(ValueError):
        Spec(tool='mlperf', **kwargs)


def test_kv_matrix_does_not_expand_training_axes():
    matrix = ParameterMatrix(tool='mlperf', mlperf_scenario='kvcache', mlperf_model='tiny-1b',
                             runtime_seconds=[5, 10], total_size='1GiB', concurrency=[1, 2])
    specs = list(matrix.expand())
    assert len(specs) == 4
    assert {s.runtime_seconds for s in specs} == {5, 10}


def test_matrix_rejects_cross_scene_options_instead_of_dropping_them():
    with pytest.raises(ValueError):
        ParameterMatrix(tool='mlperf',mlperf_scenario='kvcache',mlperf_model='tiny-1b',checkpoint_count=3)


@pytest.mark.parametrize('test', [
    {'tool':'mlperf','mlperf_scenario':'checkpointing','mlperf_model':'custom','checkpoint_mode':'read','checkpoint_size':'16MiB'},
    {'tool':'mlperf','mlperf_scenario':'kvcache','mlperf_model':'tiny-1b','runtime_seconds':5,'total_size':'1GiB'},
])
def test_api_preview_and_rerun_preserve_v3_scenario(admin, test):
    payload=setup(admin)
    payload['tests']=[test]
    preview=admin.post('/api/v1/performance/preview',json=payload)
    assert preview.status_code == 200, preview.text
    assert '--mlperf-scenario '+test['mlperf_scenario'] in preview.json()['tests'][0]['command']
    created=admin.post('/api/v1/performance/runs',json=payload)
    assert created.status_code == 202, created.text
    identifier=created.json()['id']
    admin.post('/api/v1/performance/runs/'+identifier+'/cancel')
    admin.app.state.performance_manager.process(identifier)
    rerun=admin.post('/api/v1/performance/runs/'+identifier+'/rerun')
    assert rerun.status_code == 202, rerun.text
    assert rerun.json()['snapshot']['tests'][0]['mlperf_scenario'] == test['mlperf_scenario']


def checkpoint_report(tmp_path):
    expected = Spec(tool='mlperf', mlperf_scenario='checkpointing', mlperf_model='custom',
                    checkpoint_size='16MiB', checkpoint_mode='read').model_dump()
    plan = {**expected, 'format': 'dtt-mlperf-v2', 'engine_version': '3.0.46',
            'checkpoint_size': 16 * 1024**2, 'preparation_required': True, 'file_count': 0}
    (tmp_path / 'native.json').write_text('{}')
    raw = {'format': 'dtt-mlperf-v2', 'engine_version': '3.0.46', 'plan': plan, 'status': 'passed',
           'preparation': {'status': 'passed'}, 'rounds': [{'round': 1, 'status': 'passed',
              'metrics': {'read_gib_per_second': 1.5, 'read_seconds': .1, 'checkpoint_gib': .015625},
              'native_reports': ['native.json']}]}
    return expected, raw


def test_v2_checkpoint_report(tmp_path):
    expected, raw = checkpoint_report(tmp_path)
    result = mlperf_summary(raw, expected, tmp_path)
    assert result['status'] == 'passed'
    assert result['statistics']['metrics']['read_gib_per_second']['mean'] == 1.5


@pytest.mark.parametrize('mutation', ['version', 'scene', 'phase', 'nonfinite', 'preparation'])
def test_v2_rejects_invalid_evidence(tmp_path, mutation):
    expected, raw = checkpoint_report(tmp_path)
    if mutation == 'version': raw['plan']['engine_version'] = '2.0'
    if mutation == 'scene': raw['plan']['mlperf_scenario'] = 'kvcache'
    if mutation == 'phase': raw['rounds'][0]['metrics'].pop('read_seconds')
    if mutation == 'nonfinite': raw['rounds'][0]['metrics']['read_seconds'] = float('nan')
    if mutation == 'preparation': raw['preparation'] = None
    with pytest.raises(ValueError):
        mlperf_summary(raw, expected, tmp_path)
