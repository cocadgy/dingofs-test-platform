import time
import multiprocessing
from unittest.mock import MagicMock
import pytest
from dingofs_platform.inventory.ssh_transport import (
    SSHConfig,
    CommandResult,
    CollectionError,
    execute,
    run_session,
    supervise,
)


def stall(config, commands, timeout_s, max_bytes, send):
    time.sleep(10)


def oversized(config, commands, timeout_s, max_bytes, send):
    send.send_bytes(b"x" * (max_bytes + 1))


def success_worker(config, commands, timeout_s, max_bytes, send):
    import json

    send.send_bytes(
        json.dumps(
            {"results": {"cpu": {"stdout": "ok", "stderr": "", "returncode": 0}}}
        ).encode()
    )


def test_total_deadline_including_blocked_dns():
    start = time.monotonic()
    before = {p.pid for p in multiprocessing.active_children()}
    with pytest.raises(CollectionError, match="timeout"):
        supervise(None, {}, 0.3, 1024, worker=stall)
    assert time.monotonic() - start < 3
    assert {p.pid for p in multiprocessing.active_children()} == before


def test_ipc_output_limit():
    with pytest.raises(CollectionError, match="output_limit"):
        supervise(None, {}, 3, 1024, worker=oversized)


def test_success_worker():
    assert supervise(None, {}, 3, 1024, worker=success_worker)["cpu"] == CommandResult(
        "ok", "", 0
    )


@pytest.fixture
def config():
    return SSHConfig("host", 22, "user", " PRIVATE ", "/known_hosts")


def test_unknown_host_is_automatically_trusted_and_closed(config):
    import paramiko
    client = MagicMock()
    run_session(config, {}, 30, 1024, client_factory=lambda: client)
    assert isinstance(client.set_missing_host_key_policy.call_args.args[0], paramiko.AutoAddPolicy)
    client.load_host_keys.assert_not_called()
    assert client.connect.call_args.kwargs["allow_agent"] is False
    assert client.connect.call_args.kwargs["look_for_keys"] is False
    client.close.assert_called_once()


@pytest.mark.parametrize(
    "failure,code",
    [
        ("auth", "authentication_failed"),
        ("host", "host_key_changed"),
    ],
)
def test_errors_do_not_leak_password(config, failure, code):
    import paramiko

    client = MagicMock()
    if failure == "auth":
        client.connect.side_effect = paramiko.AuthenticationException(" PRIVATE ")
    elif failure == "host":
        client.connect.side_effect = paramiko.BadHostKeyException("host", None, None)
    else:
        client.load_host_keys.side_effect = PermissionError(" PRIVATE ")
    with pytest.raises(CollectionError, match=code) as error:
        run_session(config, {}, 30, 1024, client_factory=lambda: client)
    assert "PRIVATE" not in str(error.value)
    client.close.assert_called_once()


def test_streams_are_drained_with_shared_limit(config):
    client = MagicMock()
    channel = MagicMock()
    client.get_transport.return_value.open_session.return_value = channel
    channel.recv_ready.return_value = True
    channel.recv.return_value = b"x" * 20
    with pytest.raises(CollectionError, match="output_limit"):
        run_session(config, {"cpu": "lscpu -J"}, 30, 10, client_factory=lambda: client)
    client.close.assert_called_once()
    channel.close.assert_called_once()


def test_real_loopback_ssh_handshake_and_command(tmp_path):
    import socket, threading, paramiko

    key = paramiko.RSAKey.generate(2048)
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    listener.settimeout(5)
    port = listener.getsockname()[1]
    known = tmp_path / "known_hosts"
    known.write_text(f"[127.0.0.1]:{port} {key.get_name()} {key.get_base64()}\n")
    command_seen = []
    event = threading.Event()
    errors = []

    class Server(paramiko.ServerInterface):
        def check_auth_password(self, username, password):
            return (
                paramiko.AUTH_SUCCESSFUL
                if username == "tester" and password == " secret "
                else paramiko.AUTH_FAILED
            )

        def get_allowed_auths(self, username):
            return "password"

        def check_channel_request(self, kind, chanid):
            return (
                paramiko.OPEN_SUCCEEDED
                if kind == "session"
                else paramiko.OPEN_FAILED_ADMINISTRATIVELY_PROHIBITED
            )

        def check_channel_exec_request(self, channel, command):
            command_seen.append(command)
            event.set()
            return True

    def serve():
        transport = None
        try:
            connection, _ = listener.accept()
            transport = paramiko.Transport(connection)
            transport.add_server_key(key)
            transport.start_server(server=Server())
            channel = transport.accept(5)
            if channel is None or not event.wait(5):
                raise RuntimeError("no command")
            channel.sendall(b"local-only probe\n")
            channel.send_exit_status(0)
            channel.shutdown_write()
            time.sleep(0.1)
            channel.close()
        except Exception as exc:
            errors.append(type(exc).__name__)
        finally:
            if transport:
                transport.close()
            listener.close()

    thread = threading.Thread(target=serve, daemon=True)
    thread.start()
    try:
        result = execute(
            SSHConfig("127.0.0.1", port, "tester", " secret ", str(known)),
            {"cpu": "lscpu -J"},
            timeout_s=5,
        )
        assert result["cpu"] == CommandResult("local-only probe\n", "", 0)
        assert command_seen == [b"LC_ALL=C; export LC_ALL; lscpu -J"]
    finally:
        listener.close()
        thread.join(6)
    assert not errors and not thread.is_alive()
