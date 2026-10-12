"""IPC framing must allow JSON escaping without raising the SSH byte budget."""
import json

import pytest

from dingofs_platform.clusters import transport
from dingofs_platform.clusters.transport import _worker as original_worker


def encoded_result_worker(send, config, command, password, account, timeout, max_bytes):
    # Run the actual worker JSON encoder in a child; no SSH connection is made.
    transport.run_session = lambda *args: transport.ClusterCommandResult(
        transport.ExecutionIdentity("root", "/root", "/bin/dingo"),
        command.resource_script, "", 0,
    )
    original_worker(send, config, command, password, account, timeout, max_bytes)


@pytest.mark.parametrize("stdout", [
    json.dumps({"fs_infos": [{"fs_name": "daily", "fs_id": 7}] * 20000}),
    "\x00" * (128 * 1024),
], ids=["filesystem-json", "control-characters"])
def test_ipc_encoding_overhead_does_not_reject_bounded_output(monkeypatch, stdout):
    monkeypatch.setattr(transport, "_worker", encoded_result_worker)
    result = transport.execute_cluster(
        None,
        transport.ClusterCommand("resource", "root", "main", resource_script=stdout),
        max_bytes=len(stdout.encode()),
        timeout_s=5,
    )
    assert result.stdout == stdout
    assert result.returncode == 0


def test_raw_ssh_output_still_cannot_exceed_requested_budget():
    class Channel:
        data = b"x" * 1025

        def recv_ready(self):
            return bool(self.data)

        def recv(self, n):
            value, self.data = self.data[:n], self.data[n:]
            return value

        def recv_stderr_ready(self):
            return False

        def recv_stderr(self, n):
            return b""

        def exit_status_ready(self):
            return not self.data

        def recv_exit_status(self):
            return 0

    with pytest.raises(transport.ClusterExecutionError, match="output_limit"):
        transport.read_channel(Channel(), "probe", None, None, 1, 1024)
