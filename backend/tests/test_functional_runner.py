import json
from pathlib import Path
from dingofs_platform.functional.remote_runner import run


def request(root):
    root.mkdir()
    (root/'request.json').write_text(json.dumps({
        'selected':{'quota':['a.yaml']},'hashes':{'quota':{'a.yaml':'0'*64}},
        'env_name':'env_test','mds_addr':'127.0.0.1:6900','retries':0,
        'binaries':{},'timeout_seconds':30}))


def test_cancel_before_launch_never_starts_dtt(tmp_path, monkeypatch):
    monkeypatch.setenv('HOME',str(tmp_path))
    root=tmp_path/'job';request(root)
    dtt=tmp_path/'.local/share/dingofs-platform/tools/dtt/current/dtt'
    dtt.parent.mkdir(parents=True)
    dtt.write_text('#!/bin/sh\ntouch '+str(tmp_path/'started')+'\n')
    dtt.chmod(0o755)
    (root/'cancel').touch()
    run(root)
    assert json.loads((root/'state.json').read_text())['state']=='cancelled'
    assert not (tmp_path/'started').exists()


def test_one_exact_task_emits_terminal_state(tmp_path, monkeypatch):
    monkeypatch.setenv('HOME',str(tmp_path))
    root=tmp_path/'job';request(root)
    dtt=tmp_path/'.local/share/dingofs-platform/tools/dtt/current/dtt'
    dtt.parent.mkdir(parents=True)
    dtt.write_text("#!/bin/sh\nprintf 'dtt invoked\\n'\nmkdir -p '"+str(root/'output')+"'\nprintf '%s\\n' '{\"type\":\"case_finished\",\"module\":\"quota\",\"case\":\"a.yaml\",\"status\":\"PASS\"}' > '"+str(root/'output'/'functional-events.jsonl')+"'\nexit 0\n")
    dtt.chmod(0o755)
    run(root)
    state=json.loads((root/'state.json').read_text())
    assert state['state']=='success'
    assert state['result']['returncode']==0
    assert state['completed']==1
    assert state['result']['cases'][0]['status']=='PASS'
    assert (root/'plan.json').is_file()
    assert 'dtt invoked' in (root/'console.log').read_text()


def test_binary_overrides_are_passed_to_dtt_and_recorded(tmp_path,monkeypatch):
    monkeypatch.setenv('HOME',str(tmp_path));monkeypatch.setenv('DTT_CACHE_BINARY','/stale/cache')
    root=tmp_path/'job';request(root)
    data=json.loads((root/'request.json').read_text())
    data['binaries']={'dingo-client':'/build/client candidate','dingo-mds-client':'/build/mds'}
    (root/'request.json').write_text(json.dumps(data))
    dtt=tmp_path/'.local/share/dingofs-platform/tools/dtt/current/dtt';dtt.parent.mkdir(parents=True)
    dtt.write_text('#!/bin/sh\nprintf "CLIENT=%s\\nCACHE=%s\\nMDS=%s\\n" "$DTT_CLIENT_BINARY" "$DTT_CACHE_BINARY" "$DTT_MDS_CLIENT_BINARY"\n')
    dtt.chmod(0o755);run(root)
    log=(root/'console.log').read_text()
    assert 'CLIENT=/build/client candidate' in log
    assert 'MDS=/build/mds' in log
    assert '/stale/cache' not in log
    assert 'dingo-client=/build/client candidate' in log


def test_zero_exit_with_suite_error_is_not_success(tmp_path, monkeypatch):
    _assert_incomplete_run_fails(tmp_path,monkeypatch,[{'type':'suite_finished','suite_errors':1}], '套件')


def test_zero_exit_without_case_results_is_not_success(tmp_path, monkeypatch):
    _assert_incomplete_run_fails(tmp_path,monkeypatch,[], '用例结果不完整')


def test_zero_exit_with_failed_case_is_not_success(tmp_path, monkeypatch):
    _assert_incomplete_run_fails(tmp_path,monkeypatch,[{'type':'case_finished','module':'quota','case':'a.yaml','status':'FAIL'}], '用例失败')


def _assert_incomplete_run_fails(tmp_path,monkeypatch,events,reason):
    import shlex
    monkeypatch.setenv('HOME',str(tmp_path));root=tmp_path/'job';request(root)
    dtt=tmp_path/'.local/share/dingofs-platform/tools/dtt/current/dtt';dtt.parent.mkdir(parents=True)
    output='\n'.join(json.dumps(event) for event in events)+'\n'
    dtt.write_text('#!/bin/sh\nprintf %s '+shlex.quote(output)+' > '+shlex.quote(str(root/'output/functional-events.jsonl'))+'\nexit 0\n')
    dtt.chmod(0o755);run(root)
    state=json.loads((root/'state.json').read_text())
    assert state['state']=='failed'
    assert reason in state['error']
