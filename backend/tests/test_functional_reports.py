"""Report isolation and complete-buffer redaction; no SSH or workloads."""
from types import SimpleNamespace
import socket
import subprocess

import pytest

from dingofs_platform.errors import Problem


@pytest.fixture(autouse=True)
def no_remote_io(monkeypatch):
    def denied(*args, **kwargs):
        raise AssertionError('remote I/O forbidden')
    monkeypatch.setattr(socket.socket, 'connect', denied)
    monkeypatch.setattr(subprocess, 'Popen', denied)


def records(tmp_path):
    output = tmp_path / 'output' / 'parent' / 'child'
    output.mkdir(parents=True)
    parent = SimpleNamespace(id='parent', version=2, creator_id='owner')
    child = SimpleNamespace(id='child', run_id='parent',
        remote_identity={'root': str(tmp_path / 'supervisor/child'), 'output': str(output), 'remote_state': {
            'verified_report': {'child_id': 'child', 'html_path': 'report/index.html'}}},
        result={'report_status': 'ready', 'report_path': 'report/index.html'})
    actor = SimpleNamespace(id='owner', role='member', disabled=False, deleted=False)
    return parent, child, actor, output


def test_module_report_never_falls_back_to_latest(tmp_path):
    from dingofs_platform.functional.reports import read_report_file
    parent, child, actor, output = records(tmp_path)
    other = output / 'int_allure_report' / 'allure-report-latest'
    other.mkdir(parents=True)
    (other / 'index.html').write_text('other report')
    with pytest.raises(Problem) as exc:
        read_report_file(output, 'report/index.html', 'index.html')
    assert exc.value.status == 404
    (output / 'report').mkdir()
    (output / 'report/index.html').write_text('exact child')
    assert read_report_file(output, 'report/index.html', 'index.html') == b'exact child'


@pytest.mark.parametrize('path', ['../secret', '/etc/passwd', 'a/../../x', 'a\\b', 'a\x00b', './index.html', 'a//b'])
def test_report_path_and_owner_guard(tmp_path, path):
    from dingofs_platform.functional.reports import report_location
    parent, child, actor, output = records(tmp_path)
    with pytest.raises(Problem) as exc:
        report_location(parent, child, actor, path)
    assert exc.value.status == 404


def test_report_requires_parent_owner_and_matching_child(tmp_path):
    from dingofs_platform.functional.reports import report_location
    parent, child, actor, output = records(tmp_path)
    actor.id = 'stranger'
    with pytest.raises(Problem) as exc:
        report_location(parent, child, actor, 'index.html')
    assert exc.value.status == 403
    actor.id = 'owner'
    child.run_id = 'other'
    with pytest.raises(Problem) as exc:
        report_location(parent, child, actor, 'index.html')
    assert exc.value.status == 404


def test_report_requires_verified_html_not_raw_allure_results(tmp_path):
    from dingofs_platform.functional.reports import report_location
    parent, child, actor, output = records(tmp_path)
    assert report_location(parent, child, actor, 'index.html') == (str(output), 'report/index.html', 'index.html')
    child.remote_identity['remote_state'] = {}
    with pytest.raises(Problem) as exc:
        report_location(parent, child, actor, 'index.html')
    assert exc.value.status == 404


def test_report_output_must_match_supervisor_sibling_directory(tmp_path):
    from dingofs_platform.functional.reports import report_location
    parent, child, actor, output = records(tmp_path)
    child.remote_identity['root'] = str(tmp_path / 'other/supervisor/child')
    with pytest.raises(Problem) as exc:
        report_location(parent, child, actor, 'index.html')
    assert exc.value.status == 404


@pytest.mark.parametrize('symlink_kind', ['file', 'directory', 'output'])
def test_report_rejects_symlinks_even_to_in_tree_files(tmp_path, symlink_kind):
    from dingofs_platform.functional.reports import read_report_file
    output = tmp_path / 'output'
    output.mkdir()
    (output / 'real').mkdir()
    (output / 'real/index.html').write_text('private')
    if symlink_kind == 'file':
        (output / 'real/link.html').symlink_to('index.html')
        requested, html = 'link.html', 'real/index.html'
    elif symlink_kind == 'directory':
        (output / 'link').symlink_to('real')
        requested, html = 'index.html', 'link/index.html'
    else:
        (tmp_path / 'alias').symlink_to(output)
        output = tmp_path / 'alias'
        requested, html = 'index.html', 'real/index.html'
    with pytest.raises(Problem) as exc:
        read_report_file(output, html, requested)
    assert exc.value.status == 404


def test_chunked_secret_not_downloadable():
    from dingofs_platform.functional.reports import safe_report_bytes
    secret = 'sample-credential'
    data, media = safe_report_bytes('index.html', [b'<p>sample-cre', b'dential</p>'], [secret])
    assert data == b'<p>[REDACTED]</p>'
    assert media == 'text/html'
    with pytest.raises(Problem) as exc:
        safe_report_bytes('attachment.bin', [b'\x89PNGsample-credential'], [secret])
    assert exc.value.status == 404


def test_redaction_unavailable_or_invalid_text_refuses_download():
    from dingofs_platform.functional.reports import safe_report_bytes
    for chunks, secrets in [([b'ok'], None), ([b'\xffsecret'], ['secret']), ([b'\x00secret'], ['secret'])]:
        with pytest.raises(Problem):
            safe_report_bytes('attachment.txt', chunks, secrets)


def test_encoded_credentials_are_redacted():
    import html
    import json
    import shlex
    from urllib.parse import quote
    from dingofs_platform.functional.reports import safe_report_bytes
    secret = 'a"b c<d\'e'
    variants = [secret, json.dumps(secret)[1:-1], quote(secret, safe=''), html.escape(secret), shlex.quote(secret)]
    data, _ = safe_report_bytes('data.json', ['|'.join(variants).encode()], [secret])
    for value in variants:
        assert value.encode() not in data


def test_remote_report_reader_executes_same_containment_guard(tmp_path, capsys):
    import base64
    import json
    from dingofs_platform.functional.reports import report_read_code
    output = tmp_path / 'output'
    (output / 'html').mkdir(parents=True)
    (output / 'html/index.html').write_text('verified report')
    code = report_read_code(str(output), 'html/index.html', 'index.html')
    exec(compile(code, '<report-test>', 'exec'), {})
    assert base64.b64decode(json.loads(capsys.readouterr().out)['data']) == b'verified report'
    (output / 'html/escape.txt').symlink_to('/etc/passwd')
    exec(compile(report_read_code(str(output), 'html/index.html', 'escape.txt'), '<report-test>', 'exec'), {})
    assert json.loads(capsys.readouterr().out) == {'missing': True}
