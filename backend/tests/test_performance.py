import pytest
from pydantic import ValidationError
from dingofs_platform.performance.schemas import TestSpec as BenchmarkSpec, RunInput
from dingofs_platform.performance.commands import argv_for


def test_plan_resolves_total_and_uses_argv():
    spec=BenchmarkSpec(tool='fio', total_size='16MiB', file_count=4, concurrency=2)
    assert spec.file_size=='4194304'
    args=argv_for(spec, '/tmp/data space', '/tmp/report', '/opt/dtt')
    assert args[args.index('-m')+1]=='/tmp/data space'
    assert args[args.index('--file-count')+1]=='4'


@pytest.mark.parametrize('values',[
    dict(file_size='4KiB',block_size='8KiB'),dict(direct=True,file_size='1KiB',block_size='1KiB'),
    dict(concurrency=8,file_count=2),dict(file_size='1MiB',file_count=2,total_size='3MiB'),
    dict(file_size='1G;touch /tmp/x'),dict(rw='write',read_percent=50),
])
def test_invalid_parameters_rejected(values):
    with pytest.raises(ValidationError):BenchmarkSpec(tool='fio',**values)


@pytest.mark.parametrize('path',['/','/dev/sda','/tmp/../etc','relative','/tmp/x\ncmd','/tmp/a:b'])
def test_invalid_target_paths_rejected(path):
    with pytest.raises(ValidationError):RunInput(name='test',machine_id='m',target_path=path,tests=[{'tool':'fio'}])


def test_duplicate_tools_rejected():
    with pytest.raises(ValidationError):RunInput(name='t',machine_id='m',target_path='/tmp/test',tests=[{'tool':'fio'},{'tool':'fio'}])
