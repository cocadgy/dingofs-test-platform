import json
import os
from pathlib import Path
import subprocess

from dingofs_platform.tool_packages import automatic


def run_helper(tmp_path, exit_code=0):
    stub=tmp_path/'scp'
    stub.write_text('#!/usr/bin/env python3\nimport os,sys,subprocess\nfrom pathlib import Path\nassert "test-password" not in repr(sys.argv)\nassert subprocess.check_output([os.environ["SSH_ASKPASS"]]).decode()=="test-password"\nPath(os.environ["RECORD"]).write_text(os.environ["SSH_ASKPASS"])\nprint("image.tar 100% 10MB 50MB/s")\nprint("permission denied" if '+str(exit_code)+' else "done")\nsys.exit('+str(exit_code)+')\n')
    stub.chmod(0o755)
    request=dict(host='127.0.0.1',port=2222,username='user',password='test-password',source='/tmp/image.tar',destination='/tmp/dest/image.tar',timeout=5)
    result=subprocess.run(['python3',str(Path(automatic.__file__).with_name('scp_helper.py'))],input=json.dumps(request),text=True,capture_output=True,env=dict(os.environ,PATH=str(tmp_path)+':'+os.environ['PATH'],RECORD=str(tmp_path/'record')),timeout=10)
    assert 'test-password' not in result.stdout+result.stderr
    assert not Path((tmp_path/'record').read_text()).exists()
    return result


def test_scp_progress_and_secret_cleanup(tmp_path):
    result=run_helper(tmp_path)
    assert result.returncode==0,result.stderr
    assert '50MB/s' in result.stdout
    assert json.loads(result.stdout.splitlines()[-1])['success']


def test_scp_failure_is_visible_and_cleans_credentials(tmp_path):
    result=run_helper(tmp_path,1)
    assert result.returncode!=0
    assert 'SCP 传输失败' in result.stderr
    assert 'permission denied' in result.stderr
