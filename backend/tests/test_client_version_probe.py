import hashlib
import pytest
from dingofs_platform.resources import cache_binary as binary

VERSION = 'v5.2, ci/cd build-v5.2:9232535 + release'

def executable(tmp_path, output=VERSION, code=1):
    path = tmp_path / 'dingo-client'
    path.write_text("#!/bin/sh\nprintf '%s\\n' '" + output + "'\nexit " + str(code) + "\n")
    path.chmod(0o700)
    return path

def test_client_path_accepts_known_version_exit_one(tmp_path):
    path = executable(tmp_path)
    info = binary.prepare_cache_binary({'binary_source': 'path', 'binary_directory': str(tmp_path)}, component='dingo-client')
    assert info['version'] == VERSION
    assert info['path'] == str(path)

@pytest.mark.parametrize('output,code', [('error loading shared library', 1), ('', 1), (VERSION, 2), (VERSION + '\nFatal error', 1)])
def test_client_real_errors_are_not_accepted(tmp_path, output, code):
    executable(tmp_path, output, code)
    with pytest.raises(ValueError, match='dingo-client'):
        binary.prepare_cache_binary({'binary_source': 'path', 'binary_directory': str(tmp_path)}, component='dingo-client')

def test_tag_temporary_probe_uses_client_version_rules(tmp_path, monkeypatch):
    path = executable(tmp_path)
    monkeypatch.setattr(binary.Path, 'home', lambda: tmp_path)
    digest = 'sha256:' + 'a' * 64
    info = binary.prepare_cache_binary({'binary_source': 'tag', 'binary_tag': 'v5.2-latest',
        'binary_digest': digest, 'binary_upload': {'path': str(path), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}}, component='dingo-client')
    assert info['version'] == VERSION
    assert 'client-binaries' in info['path']
