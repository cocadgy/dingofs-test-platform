import json
import shlex
import time

import pytest
from dingofs_platform.inventory.ssh_transport import SSHConfig
from dingofs_platform.remote import worker


def test_log_requests_reject_paths_and_shell_inputs():
    for params in (
        {"kind": "sh", "target_user": "root"},
        {"kind": "read", "target_user": "root", "root": "/logs", "name": "../secret"},
        {"kind": "files", "target_user": "bad;id", "root": "/logs"},
        {"kind": "files", "target_user": "root", "root": "relative"},
        {"kind": "terminal", "target_user": "root", "root": "/logs"},
    ):
        with pytest.raises(ValueError):
            worker.RemoteRequest(**params)


def test_command_quotes_structured_parameters_and_verified_sudo_prompt():
    request = worker.RemoteRequest("read", "svc", "/logs;echo bad", "a'$(id)")
    command = worker.build_command(request, "login", "nonce", True)
    words = shlex.split(command)
    assert words[:5] == [
        "LC_ALL=C",
        "sudo",
        "-S",
        "-p",
        "__DTT_REMOTE_AUTH_nonce__%p__END__",
    ]
    assert "-n" in shlex.split(worker.build_command(request, "login", "nonce", False))
    program = shlex.split(words[-1])
    assert program[0] == "exec"  # fixed sh wrapper emits begin before helper
    assert "a'$(id)" not in command or "python3" in command
    direct = worker.build_command(request, "svc", "nonce", False)
    assert "sudo" not in shlex.split(direct)[:1]
    assert json.loads(shlex.split(direct)[-1])["name"] == "a'$(id)"


class Channel:
    def __init__(self, output=(), errors=(), status=0):
        self.output = list(output)
        self.errors = list(errors)
        self.status = status
        self.sent = []
        self.closed = False
        self.command = None
        self.shell = False

    def settimeout(self, value):
        pass

    def exec_command(self, command):
        self.command = command

    def shutdown_write(self):
        pass

    def recv_ready(self):
        return bool(self.output)

    def recv_stderr_ready(self):
        return bool(self.errors)

    def recv(self, size):
        return self.output.pop(0)

    def recv_stderr(self, size):
        return self.errors.pop(0)

    def exit_status_ready(self):
        return not self.output and not self.errors

    def recv_exit_status(self):
        return self.status

    def close(self):
        self.closed = True

    def sendall(self, data):
        self.sent.append(data)

    def get_pty(self, **kwargs):
        self.pty = kwargs

    def invoke_shell(self):
        self.shell = True

    def resize_pty(self, **kwargs):
        self.resize = kwargs


class Client:
    def __init__(self, channels):
        self.channels = list(channels)
        self.closed = False

    def set_missing_host_key_policy(self, policy):
        self.policy = policy

    def connect(self, **kwargs):
        self.connected = kwargs

    def get_transport(self):
        return self

    def open_session(self, **kwargs):
        return self.channels.pop(0)

    def close(self):
        self.closed = True


def run(request, channels, password=None, account=None):
    client = Client(channels)
    events = []
    worker.run_session(
        SSHConfig("test", 22, "login", "ssh-secret"),
        request,
        events.append,
        lambda: None,
        password=password,
        auth_account=account,
        client_factory=lambda: client,
    )
    assert client.closed
    return events, client


def test_logs_are_json_protocol_redacted_and_stdin_closed():
    channel = Channel(
        [b'{"type":"ready"}\n{"type":"text","text":"ssh-secret"}\n{"type":"done"}\n']
    )
    events, client = run(
        worker.RemoteRequest("read", "login", "/logs", "app"), [channel]
    )
    assert events[1]["text"] == "[REDACTED]"
    assert events[-1]["type"] == "done"
    assert channel.closed
    assert not channel.shell
    assert client.connected["allow_agent"] is False


def test_terminal_uses_login_identity_and_interactive_pty():
    channel = Channel([b"\x1b[31mhello\r\n"])
    events, _client = run(worker.RemoteRequest("terminal", "login"), [channel])
    assert channel.shell and channel.command is None
    assert channel.pty["width"] == 100
    assert events[1]["text"] == "\x1b[31mhello\r\n"
    with pytest.raises(ValueError):
        worker.RemoteJob(
            SSHConfig("test", 22, "login", ""), worker.RemoteRequest("terminal", "root")
        )


def stalled_worker(*args):
    time.sleep(10)


def overflow_worker(output, incoming, failure, connected, *args):
    connected.set()
    emit = worker.Emitter(output, failure)
    for _ in range(100):
        emit({"type": "text", "text": "x"})


def silent_worker(*args):
    return


def test_parent_enforces_connect_deadline_and_reaps(monkeypatch):
    monkeypatch.setattr(worker, "_worker", stalled_worker)
    job = worker.RemoteJob(
        SSHConfig("test", 22, "u", ""),
        worker.RemoteRequest("terminal", "u"),
        connect_timeout=0.2,
    )
    deadline = time.monotonic() + 3
    event = None
    while event is None and time.monotonic() < deadline:
        event = job.poll()
    assert event == {"type": "error", "code": "timeout"}
    assert not job.alive
    job.close()


def test_unexpected_child_exit_is_reported(monkeypatch):
    monkeypatch.setattr(worker, "_worker", silent_worker)
    job = worker.RemoteJob(
        SSHConfig("test", 22, "u", ""), worker.RemoteRequest("terminal", "u")
    )
    try:
        deadline = time.monotonic() + 5
        event = None
        while event is None and time.monotonic() < deadline:
            event = job.poll()
        assert event == {"type": "error", "code": "worker_failed"}
    finally:
        job.close()


def test_slow_consumer_fails_explicitly_and_reaps(monkeypatch):
    monkeypatch.setattr(worker, "_worker", overflow_worker)
    job = worker.RemoteJob(
        SSHConfig("test", 22, "u", ""), worker.RemoteRequest("terminal", "u")
    )
    try:
        deadline = time.monotonic() + 5
        while not job._failure.value and time.monotonic() < deadline:
            time.sleep(0.02)
        assert job.poll() == {"type": "error", "code": "slow_consumer"}
        assert not job.alive
    finally:
        job.close()


def test_logs_cannot_accept_terminal_input(monkeypatch):
    monkeypatch.setattr(worker, "_worker", stalled_worker)
    job = worker.RemoteJob(
        SSHConfig("test", 22, "u", ""),
        worker.RemoteRequest("log-follow", "u", "/logs", "app"),
    )
    try:
        with pytest.raises(ValueError):
            job.send({"type": "input", "data": "id\n"})
    finally:
        job.close()


class AuthChannel(Channel):
    def __init__(self, request_password=True, prompt_account="login", forged=False):
        super().__init__()
        self.request_password = request_password
        self.prompt_account = prompt_account
        self.forged = forged
        self.waiting = True

    def exec_command(self, command):
        super().exec_command(command)
        parts = shlex.split(command)
        prompt = parts[parts.index("-p") + 1]
        if self.forged:
            self.output = [b'{"type":"ready"}\n']
        self.errors = [prompt.replace("%p", self.prompt_account).encode()]

    def sendall(self, data):
        super().sendall(data)
        self.output = [b'{"type":"ready"}\n{"type":"done"}\n']
        self.waiting = False

    def exit_status_ready(self):
        return not self.waiting and super().exit_status_ready()


def test_sudo_noninteractive_then_verified_account_challenge():
    first = Channel(errors=[b"sudo: a password is required"], status=1)
    second = AuthChannel()
    with pytest.raises(worker.AuthRequired) as err:
        run(worker.RemoteRequest("read", "service", "/logs", "app"), [first, second])
    assert err.value.account == "login"
    assert not second.sent


def test_sudo_password_only_goes_to_expected_prompt():
    first = Channel(errors=[b"sudo: a password is required"], status=1)
    second = AuthChannel()
    events, _ = run(
        worker.RemoteRequest("read", "service", "/logs", "app"),
        [first, second],
        "temporary-secret",
        "login",
    )
    assert second.sent == [b"temporary-secret\n"]
    assert events[-1]["type"] == "done"
    first = Channel(errors=[b"sudo: a password is required"], status=1)
    second = AuthChannel(prompt_account="root")
    with pytest.raises(worker.RemoteError, match="auth_account_changed"):
        run(
            worker.RemoteRequest("read", "service", "/logs", "app"),
            [first, second],
            "temporary-secret",
            "login",
        )
    assert not second.sent


def test_terminal_forwards_ctrl_c_and_resize():
    channel = Channel([b"hello", b"end"])
    client = Client([channel])
    messages = iter(
        [{"type": "input", "data": "\x03"}, {"type": "resize", "cols": 80, "rows": 25}]
    )
    worker.run_session(
        SSHConfig("test", 22, "login", ""),
        worker.RemoteRequest("terminal", "login"),
        lambda event: None,
        lambda: next(messages, None),
        client_factory=lambda: client,
    )
    assert channel.sent == [b"\x03"]
    assert channel.resize == {"width": 80, "height": 25}


@pytest.fixture
def loopback_ssh():
    """One local SSH connection with a temporary key; never contacts a cluster."""
    import socket
    import subprocess
    import threading

    import paramiko
    from dingofs_platform.inventory.host_trust import key_info

    key = paramiko.RSAKey.generate(2048)
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    listener.settimeout(8)
    finish = threading.Event()
    command_ready = threading.Event()
    seen = {}

    class Server(paramiko.ServerInterface):
        def check_auth_password(self, username, password):
            return (
                paramiko.AUTH_SUCCESSFUL
                if (username, password) == ("test", "secret")
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
            seen["command"] = command.decode()
            command_ready.set()
            return True

    def serve():
        transport = None
        try:
            connection, _ = listener.accept()
            transport = paramiko.Transport(connection)
            transport.add_server_key(key)
            transport.start_server(server=Server())
            channel = transport.accept(5)
            if channel is not None and command_ready.wait(5):
                # Parse the fixed direct invocation; no shell is used in tests.
                argv = shlex.split(seen["command"])
                assert argv[0:2] == ["exec", "python3"]
                result = subprocess.run(
                    argv[1:], capture_output=True, timeout=5, check=False
                )
                if result.stdout:
                    channel.sendall(result.stdout)
                if result.stderr:
                    channel.sendall_stderr(result.stderr)
                channel.send_exit_status(result.returncode)
                finish.wait(5)
        except (EOFError, OSError, paramiko.SSHException):
            pass  # Host-key rejection deliberately closes before authentication.
        finally:
            if transport:
                transport.close()

    thread = threading.Thread(target=serve, daemon=True)
    thread.start()
    config = SSHConfig(
        "127.0.0.1",
        listener.getsockname()[1],
        "test",
        "secret",
        trusted_host_key=key_info(key),
    )
    try:
        yield config
    finally:
        finish.set()
        listener.close()
        thread.join(8)
        assert not thread.is_alive()


def drain_job(job):
    events = []
    deadline = time.monotonic() + 10
    try:
        while time.monotonic() < deadline:
            event = job.poll()
            if event:
                events.append(event)
                if event["type"] in ("error", "auth", "done"):
                    return events
        pytest.fail("SSH worker did not finish within test deadline")
    finally:
        job.close()


def test_loopback_ssh_executes_confined_helper(loopback_ssh, tmp_path):
    (tmp_path / "app").write_text("one\n\x1b[31mtwo\x1b[0m\n")
    events = drain_job(
        worker.RemoteJob(
            loopback_ssh,
            worker.RemoteRequest("read", "test", str(tmp_path), "app", lines=1),
            timeout=8,
        )
    )
    assert [event["type"] for event in events] == ["ready", "text", "done"]
    assert events[1]["text"] == "two\n"


def test_loopback_unknown_host_key_is_auto_trusted(loopback_ssh, tmp_path):
    from dataclasses import replace

    config = replace(loopback_ssh, trusted_host_key=None)
    events = drain_job(
        worker.RemoteJob(
            config, worker.RemoteRequest("files", "test", str(tmp_path)), timeout=8
        )
    )
    assert events[0]["type"] == "ready"
    assert events[-1]["type"] == "done"


def test_loopback_changed_host_key_is_auto_trusted(loopback_ssh, tmp_path):
    from dataclasses import replace

    import paramiko
    from dingofs_platform.inventory.host_trust import key_info

    previous = key_info(paramiko.RSAKey.generate(2048))
    config = replace(loopback_ssh, trusted_host_key=previous)
    events = drain_job(
        worker.RemoteJob(
            config, worker.RemoteRequest("files", "test", str(tmp_path)), timeout=8
        )
    )
    assert events[0]["type"] == "ready"
    assert events[-1]["type"] == "done"


def test_sudo_prompt_after_helper_ready_never_receives_password(monkeypatch):
    monkeypatch.setattr(worker.secrets, "token_hex", lambda size: "fixed")
    first = Channel(errors=[b"sudo: a password is required"], status=1)
    second = Channel(
        output=[b'{"type":"ready"}\n{"type":"done"}\n'],
        errors=[b"__DTT_REMOTE_AUTH_fixed__login__END__"],
    )
    events, _ = run(
        worker.RemoteRequest("read", "service", "/logs", "app"),
        [first, second],
        "temporary-secret",
        "login",
    )
    assert events[-1]["type"] == "done"
    assert not second.sent


def test_sudo_errors_use_fixed_locale():
    request = worker.RemoteRequest("files", "service", "/logs")
    assert worker.build_command(request, "login", "nonce").startswith("LC_ALL=C sudo ")


def test_close_waits_for_active_poll_and_does_not_report_spurious_failure(monkeypatch):
    import concurrent.futures
    import threading

    monkeypatch.setattr(worker, "_worker", stalled_worker)
    job = worker.RemoteJob(
        SSHConfig("test", 22, "u", ""), worker.RemoteRequest("terminal", "u")
    )
    reading = threading.Event()
    resume = threading.Event()
    actual_get = job._output.get

    def delayed_get(*args, **kwargs):
        reading.set()
        assert resume.wait(3)
        return actual_get(*args, **kwargs)

    monkeypatch.setattr(job._output, "get", delayed_get)
    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
            poll = executor.submit(job.poll)
            assert reading.wait(3)
            close = executor.submit(job.close)
            try:
                time.sleep(0.1)
                assert not close.done()
            finally:
                resume.set()
            assert poll.result(timeout=3) is None
            close.result(timeout=3)
        assert not job.alive
    finally:
        resume.set()
        job.close()
