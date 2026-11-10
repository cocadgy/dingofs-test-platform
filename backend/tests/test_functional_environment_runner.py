from dingofs_platform.functional.transport import bootstrap_code
from dingofs_platform.functional.environments.render import render_environment

def test_bootstrap_receives_yaml_via_stdin_not_command():
    payload={'id':'test','env_name':'env_platform_abc','selected':{},'hashes':{}}
    command=bootstrap_code(payload)
    assert 'env_yaml' not in str(payload)
    assert 'json.load(sys.stdin)' in command
    assert 'O_EXCL' in command

def test_renderer_never_embeds_secret_in_snapshot():
    frozen={'environment_key':'env_platform_abc','mds_addr':'10.0.0.1:6900','client_host':'node','ssh_user':'u',
            'settings':{'mount_root':'/tmp/run','fs_prefix':'test'}}
    yaml=render_environment(frozen,{'storage_type':'s3','s3_ak':'secret-ak','s3_sk':'secret-sk','s3_endpoint':'http://s3','s3_bucketname':'bucket'},'secret-ssh')
    assert 'secret-sk' in yaml
    assert 'secret-sk' not in str(frozen)

def test_custom_yaml_removed_and_output_redacted_after_success(tmp_path,monkeypatch):
    import json
    from dingofs_platform.functional.remote_runner import run
    monkeypatch.setenv('HOME',str(tmp_path))
    root=tmp_path/'job';root.mkdir()
    key='env_platform_abc'
    (root/'request.json').write_text(json.dumps({'selected':{'basic_file_operation':['a.yaml']},
      'hashes':{'basic_file_operation':{'a.yaml':'0'*64}},'env_name':key,
      'custom_environment':True,'mds_addr':'10.0.0.1:6900','retries':0,'binaries':{},'timeout_seconds':30}))
    (root/(key+'.yaml')).write_text('secret-value')
    (root/'redactions.json').write_text(json.dumps(['secret-value']))
    dtt=tmp_path/'.local/share/dingofs-platform/tools/dtt/current/dtt';dtt.parent.mkdir(parents=True)
    event=json.dumps({'type':'case_finished','module':'basic_file_operation','case':'a.yaml','status':'PASS'})
    import shlex
    dtt.write_text('#!/bin/sh\necho secret-value\nprintf %s '+shlex.quote(event)+' > '+shlex.quote(str(root/'output/functional-events.jsonl'))+'\nexit 0\n');dtt.chmod(0o755)
    run(root)
    assert json.loads((root/'state.json').read_text())['state']=='success'
    assert not (root/(key+'.yaml')).exists()
    assert not (root/'redactions.json').exists()
    log=(root/'console.log').read_text()
    assert 'secret-value' not in log and '[REDACTED]' in log

def test_custom_yaml_removed_after_runtime_failure(tmp_path,monkeypatch):
    import json
    from dingofs_platform.functional.remote_runner import run
    monkeypatch.setenv('HOME',str(tmp_path))
    root=tmp_path/'job';root.mkdir();key='env_platform_abc'
    (root/'request.json').write_text(json.dumps({'selected':{'quota':['a.yaml']},'hashes':{'quota':{'a.yaml':'0'*64}},
      'env_name':key,'custom_environment':True,'mds_addr':'10.0.0.1:6900','retries':0,
      'binaries':{},'timeout_seconds':30}))
    (root/(key+'.yaml')).write_text('private')
    (root/'redactions.json').write_text(json.dumps(['private']))
    dtt=tmp_path/'.local/share/dingofs-platform/tools/dtt/current/dtt';dtt.parent.mkdir(parents=True)
    dtt.write_text('#!/bin/sh\nexit 2\n');dtt.chmod(0o755)
    run(root)
    assert json.loads((root/'state.json').read_text())['state']=='failed'
    assert not (root/(key+'.yaml')).exists() and not (root/'redactions.json').exists()

def test_report_redaction_handles_raw_and_json_escaped_secret():
    from dingofs_platform.functional.report_redaction import redact_report
    secret='quoted " secret'
    import json
    data=secret.encode()+b' '+json.dumps(secret)[1:-1].encode()
    sanitized=redact_report(data,[secret])
    assert b'quoted' not in sanitized
    assert sanitized.count(b'[REDACTED]')==2

def test_custom_yaml_removed_when_cancelled_before_launch(tmp_path,monkeypatch):
    import json
    from dingofs_platform.functional.remote_runner import run
    monkeypatch.setenv('HOME',str(tmp_path))
    root=tmp_path/'job';root.mkdir();key='env_platform_abc'
    (root/'request.json').write_text(json.dumps({'selected':{'quota':['a.yaml']},'hashes':{'quota':{'a.yaml':'0'*64}},
      'env_name':key,'custom_environment':True,'mds_addr':'10.0.0.1:6900','retries':0,
      'binaries':{},'timeout_seconds':30}))
    (root/(key+'.yaml')).write_text('private')
    (root/'redactions.json').write_text(json.dumps(['private']))
    (root/'cancel').touch()
    dtt=tmp_path/'.local/share/dingofs-platform/tools/dtt/current/dtt';dtt.parent.mkdir(parents=True)
    dtt.write_text('#!/bin/sh\nexit 0\n');dtt.chmod(0o755)
    run(root)
    assert json.loads((root/'state.json').read_text())['state']=='cancelled'
    assert not (root/(key+'.yaml')).exists() and not (root/'redactions.json').exists()

def test_cleanup_failure_sets_failed_state_and_keeps_diagnostic_path(tmp_path,monkeypatch):
    import json
    import pytest
    from dingofs_platform.functional.remote_runner import run
    monkeypatch.setenv('HOME',str(tmp_path))
    root=tmp_path/'job';root.mkdir();key='env_platform_abc'
    (root/'request.json').write_text(json.dumps({'selected':{},'hashes':{},'env_name':key,
      'custom_environment':True,'mds_addr':'10.0.0.1:6900','retries':0,'binaries':{},'timeout_seconds':30}))
    secret_file=root/(key+'.yaml');secret_file.write_text('private')
    (root/'redactions.json').write_text('[]')
    dtt=tmp_path/'.local/share/dingofs-platform/tools/dtt/current/dtt';dtt.parent.mkdir(parents=True)
    dtt.write_text('#!/bin/sh\nexit 0\n');dtt.chmod(0o755)
    original=type(secret_file).unlink
    def reject(self,*args,**kwargs):
        if self==secret_file:raise PermissionError('denied')
        return original(self,*args,**kwargs)
    monkeypatch.setattr(type(secret_file),'unlink',reject)
    with pytest.raises(RuntimeError,match='明文环境文件清理失败'):
        run(root)
    state=json.loads((root/'state.json').read_text())
    assert state['state']=='failed' and str(secret_file) in state['error']
