import json
import subprocess
import time
from types import SimpleNamespace

import pytest

from dingofs_platform.tool_packages.ssh_session import Remote


@pytest.mark.parametrize('bounded', [True, False])
@pytest.mark.parametrize('with_input', [True, False])
def test_large_script_streams_without_long_command_or_secret_arguments(bounded, with_input):
    class Channel:
        def __init__(self):self.payload = bytearray()
        def exec_command(self, command):
            assert len(command.encode()) < 4096
            assert 'private-input-marker' not in command
            self.command = command
        def sendall(self, data):self.payload.extend(data)
        def shutdown_write(self):
            result = subprocess.run(['bash', '-c', self.command], input=bytes(self.payload), capture_output=True, timeout=15)
            self.stdout, self.stderr, self.rc = bytearray(result.stdout), bytearray(result.stderr), result.returncode
        def recv_ready(self):return bool(self.stdout)
        def recv_stderr_ready(self):return bool(self.stderr)
        def recv(self, n):
            data=bytes(self.stdout[:n]);del self.stdout[:n];return data
        def recv_stderr(self, n):
            data=bytes(self.stderr[:n]);del self.stderr[:n];return data
        def exit_status_ready(self):return True
        def recv_exit_status(self):return self.rc
        def close(self):pass
    channel = Channel()
    transport = SimpleNamespace(open_session=lambda **kw: channel, is_active=lambda: True)
    remote = object.__new__(Remote)
    remote.client = SimpleNamespace(get_transport=lambda: transport)
    remote.deadline = time.monotonic()+60 if bounded else None
    remote.report = lambda **kw: None
    remote.label = 'test'
    code = '# ' + 'x'*600000 + '\nimport json, sys\n'
    code += 'value=json.load(sys.stdin)\n' if with_input else 'value={"empty":sys.stdin.read()==""}\n'
    code += 'print(json.dumps({"value":value,"main":__name__=="__main__"}))\n'
    data = {'secret':'private-input-marker', 'unicode':'测试', 'line':'a\nb'} if with_input else None
    result = remote.python(code, 'test', input_data=data)
    assert result == {'value': data if with_input else {'empty':True}, 'main':True}
