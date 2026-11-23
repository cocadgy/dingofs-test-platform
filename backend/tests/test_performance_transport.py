"""Exercise bootstrap/cancel ordering without launching a workload."""
import io
import json
import sys
from dingofs_platform.performance.transport import bootstrap_code, snapshot_code


def execute(code, monkeypatch, capsys, payload=None):
    monkeypatch.setattr(sys, 'stdin', io.StringIO(json.dumps(payload)))
    exec(compile(code, '<performance-rpc>', 'exec'), {})
    return json.loads(capsys.readouterr().out)


def test_cancel_missing_job_fences_a_delayed_bootstrap(tmp_path, monkeypatch, capsys):
    import subprocess
    monkeypatch.setenv('HOME', str(tmp_path))
    def forbidden(*args, **kwargs):
        raise AssertionError('cancelled bootstrap must not launch a supervisor')
    monkeypatch.setattr(subprocess, 'Popen', forbidden)
    result = execute(snapshot_code('job', True), monkeypatch, capsys)
    assert result['state'] == 'cancelled'
    root = tmp_path / '.local/share/dingofs-platform/performance/job'
    assert (root / 'cancel').exists()
    reply = execute(bootstrap_code(), monkeypatch, capsys, {'id': 'job'})
    assert reply['root'] == str(root)
    assert not (root / 'pid').exists()
    assert execute(snapshot_code('job'), monkeypatch, capsys)['state'] == 'cancelled'


def test_readonly_missing_poll_does_not_create_job(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv('HOME', str(tmp_path))
    assert execute(snapshot_code('job'), monkeypatch, capsys) == {'missing': True}
    assert not (tmp_path / '.local').exists()
