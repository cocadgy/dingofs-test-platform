import pytest
from pydantic import ValidationError
from dingofs_platform.performance.schemas import RunInput


def plan(**kwargs):
    return RunInput(name='matrix',machine_id='host',target_path='/tmp/perf',tests=[dict(tool='fio',concurrency=1,file_count=4,file_size='8KiB',block_size='4KiB',**kwargs)])


def test_matrix_cartesian_and_stable_scene_ids():
    p=plan(direct=[True,False],rw=['read','write'],rounds=[1,2])
    assert len(p.scenarios)==8
    assert len({s['id'] for s in p.scenarios})==8
    assert [s['parameters']['rw'] for s in p.scenarios]==['read','read','write','write']*2
    assert p.scenarios==plan(direct=[True,False],rw=['read','write'],rounds=[1,2]).scenarios


def test_normalized_duplicate_values_do_not_repeat_scene():
    p=RunInput(name='m',machine_id='h',target_path='/tmp/p',tests=[{'tool':'fio','concurrency':[1,1],'file_size':['4KiB','4096'],'file_count':1}])
    assert len(p.scenarios)==1


def test_mix_percent_only_expands_mixed_modes():
    p=plan(rw=['read','randrw'],read_percent=[30,70])
    assert len(p.scenarios)==3
    assert [s['parameters']['read_percent'] for s in p.scenarios]==[None,30,70]


def test_invalid_combination_is_rejected_with_parameters():
    with pytest.raises(ValidationError,match='文件数量不能小于并发度'):
        RunInput(name='m',machine_id='h',target_path='/tmp/p',tests=[{'tool':'fio','concurrency':[1,8],'file_count':4}])


def test_matrix_limit_before_expansion():
    with pytest.raises(ValidationError,match='256'):
        plan(direct=[True,False],rounds=list(range(1,101)),iodepth=[1,2])


def test_empty_axis_rejected():
    with pytest.raises(ValidationError):plan(rw=[])


def test_scalar_legacy_input_works():
    assert plan().scenarios[0]['parameters']['file_size']=='8192'
