import json
from dingofs_platform.resources import remote_helper as helper


def test_creation_failure_returns_bounded_process_logs(tmp_path, monkeypatch, capsys):
    logs=tmp_path/'logs'; logs.mkdir()
    (logs/'launcher.log').write_text('launcher failed\n')
    (logs/'dingo-cache.fatal.log.1').write_text('Fail io_uring: Operation not permitted\npassword=secret123\n')
    (logs/'huge.stdout').write_text('x'*200000)
    (logs/'outside').symlink_to('/etc/passwd')
    def fail(req): raise ValueError('resource launcher failed; inspect launcher.log')
    monkeypatch.setattr(helper,'lifecycle',fail)
    assert helper.main({'action':'cache.create','parameters':{},'record':{'log_dir':str(logs)},'resource_id':'r'})==1
    result=json.loads(capsys.readouterr().out)
    details=result['diagnostics']
    assert details['log_dir']==str(logs)
    assert any('Operation not permitted' in row['text'] for row in details['files'])
    assert all(row['filename']!='outside' for row in details['files'])
    assert 'secret123' not in json.dumps(result)
    assert len(json.dumps(result)) < 200000


def test_missing_logs_do_not_replace_original_failure(monkeypatch,capsys):
    def fail(req): raise ValueError('original failure')
    monkeypatch.setattr(helper,'lifecycle',fail)
    helper.main({'action':'mount.create','parameters':{},'record':{'log_dir':'/no/such/log-dir'},'resource_id':'r'})
    result=json.loads(capsys.readouterr().out)
    assert result['message']=='original failure'
    assert result['diagnostics']['error']
