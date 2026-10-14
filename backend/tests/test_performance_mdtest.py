import json
import pytest
from dingofs_platform.performance.schemas import RunInput, TestSpec as Spec
from dingofs_platform.performance.commands import argv_for
from dingofs_platform.performance import remote_runner as runner


def test_mdtest_matrix_and_command_use_existing_dtt_contract():
    request=RunInput(name='metadata',machine_id='m',target_path='/tmp/test',tests=[
        dict(tool='mdtest',concurrency=[1,2],file_count=[100],rounds=2,layout=['unique','shared'])])
    assert len(request.scenarios)==4
    spec=Spec(**request.scenarios[0]['parameters'])
    args=argv_for(spec,'/data path','/reports','dtt')
    assert args[:5]==['dtt','-t','mdtest','-s','custom']
    assert args[args.index('-n')+1]=='1'
    from dingofs_platform.performance.mdtest import command_for, custom_script
    assert command_for(spec)[-1] != ''
    assert '-n 100' in custom_script(spec)
    assert spec.total_size=='0'


def test_mdtest_requires_even_file_distribution():
    with pytest.raises(ValueError,match='整除'):
        Spec(tool='mdtest',concurrency=3,file_count=100)


def raw_report():
    return dict(status='PASS',plan=dict(tool='mdtest',repeats=2,workers=1,file_count=100,layout='unique'),
                results=[dict(phase=phase,round=r,success=True,operations_per_second=rate)
                         for phase in ('create','stat','remove') for r,rate in [(1,100),(2,300)]])


def test_mdtest_report_uses_arithmetic_mean_and_complete_rounds(tmp_path):
    output=tmp_path/'ai-storage-test';output.mkdir()
    (output/'summary.json').write_text(json.dumps(raw_report()))
    report,artifacts=runner.report_files(tmp_path,'mdtest')
    assert report['status']=='passed'
    assert report['statistics']['metrics']['create_ops_s']=={'mean':200,'samples':2}
    assert report['statistics']['successful_rounds']==2
    assert report['statistics']['complete'] is True
    assert 'index.html' in artifacts
    raw=raw_report();raw['results'].pop()
    (output/'summary.json').write_text(json.dumps(raw))
    report,_=runner.report_files(tmp_path,'mdtest')
    assert report['status']=='failed' and not report['statistics']['complete']
    assert report['statistics']['successful_rounds']==1


@pytest.mark.parametrize('rate',[float('nan'),float('inf'),-1,0,True])
def test_mdtest_invalid_rates_never_pass(rate):
    raw=raw_report();raw['results'][0]['operations_per_second']=rate
    assert runner.mdtest_summary(raw)['status']=='failed'


def test_all_three_tools_supported():
    payload=RunInput(name='all',machine_id='m',target_path='/tmp/test',
                     tests=[dict(tool=t) for t in ('fio','elbencho','mdtest')])
    assert {s['tool'] for s in payload.scenarios}=={'fio','elbencho','mdtest'}


def test_mdtest_mismatched_plan_is_rejected():
    with pytest.raises(ValueError,match='参数'):
        runner.mdtest_summary(raw_report(),dict(rounds=3,concurrency=1,file_count=100,layout='unique'))


def test_custom_options_matrix_and_shell_quoting():
    from dingofs_platform.performance.mdtest import command_for, custom_script
    payload=RunInput(name='custom',machine_id='m',target_path='/tmp/test',tests=[dict(
        tool='mdtest',concurrency=[1,2],file_count=8,mdtest_options={'-w':[0,4096],'-D':True,'-F':False})])
    assert len(payload.scenarios)==4
    spec=Spec(**payload.scenarios[-1]['parameters'])
    args=command_for(spec)
    assert '-D' in args and '-F' not in args and '-w' in args
    assert args[args.index('-w')+1]=='4096'
    script=custom_script(spec)
    assert 'mpirun' in script and 'python3' in script


@pytest.mark.parametrize('options',[{'--invalid':True},{'-d':'/etc'},{'-d':'../unsafe'},{'-w':-1},{'-F':True,'-D':True},{'-i':3}])
def test_custom_options_reject_invalid(options):
    with pytest.raises(ValueError):Spec(tool='mdtest',mdtest_options=options)


def test_custom_report_uses_selected_phases_not_all_phases(tmp_path):
    from dingofs_platform.performance.mdtest_runtime import parse_output
    raw='SUMMARY rate (in ops/sec): (of 2 iterations)\nOperation Max Min Mean Std Dev\nDirectory creation 300 100 200 100\nDirectory stat 0 0 0 0\nDirectory removal 0 0 0 0\nSUMMARY time (in seconds): (of 2 iterations)\nDirectory creation 3 1 2 1\n'
    tables=parse_output(raw)
    assert tables[0]['unit']=='ops/s'
    assert tables[0]['rows'][0]['mean']==200
    assert tables[1]['unit']=='s'


def test_native_task_counts_and_zero_time_preserved():
    from dingofs_platform.performance.mdtest_runtime import parse_output,summarize
    text='1 tasks, 4 files\nSUMMARY time (in seconds): (of 2 iterations)\nFile creation 0 0 0 0\n'
    tables=parse_output(text)
    assert tables[0]['tasks']==1
    spec=Spec(tool='mdtest',rounds=2).model_dump()
    result=summarize(tables,spec,0)
    assert result['statistics']['metrics']['create_seconds']['mean']==0
    assert summarize(tables+tables,spec,0)['statistics']['metrics']=={}
    assert summarize(tables,spec,1)['status']=='failed'


def test_option_dictionary_invalid_shapes_are_validation_errors():
    for value in ({'-w':[{}]}, {'-w':[]}, {'--unknown':1}):
        with pytest.raises(ValueError):RunInput(name='x',machine_id='m',target_path='/tmp/x',tests=[dict(tool='mdtest',mdtest_options=value)])


def test_write_size_and_tree_are_counted_in_disk_budget():
    assert Spec(tool='mdtest',concurrency=2,file_count=8,mdtest_options={'-w':4096}).total_size==str(8*4096)
    assert Spec(tool='mdtest',concurrency=2,file_count=8,mdtest_options={'-I':2,'-z':2,'-b':2,'-w':4096}).total_size==str(2*2*7*4096)
    with pytest.raises(ValueError):Spec(tool='mdtest',concurrency=2,mdtest_options={'-l':4})


def test_custom_command_quotes_hook_without_controller_expansion():
    import shlex
    from dingofs_platform.performance.mdtest import command_for
    hook='echo "hello world"; printf "%s" "$(whoami)"'
    argv=command_for(Spec(tool='mdtest',mdtest_options={'--run-cmd-before-phase':hook}))
    assert shlex.split(shlex.join(argv))==argv
    assert argv[argv.index('--run-cmd-before-phase')+1]==hook
