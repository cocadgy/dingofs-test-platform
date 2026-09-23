import pytest
from dingofs_platform.clusters.transport import (
    ClusterCommand,
    build_command,
    AuthenticationRequired,
    read_channel,
)


def test_fixed_commands_and_quotes():
    with pytest.raises(ValueError):
        ClusterCommand("stop", "root", "main")
    with pytest.raises(ValueError):
        ClusterCommand("status", "root;id", "main")
    s = build_command(ClusterCommand("status", "root", "main"), "test", "abc", False)
    assert (
        "sudo -n -i -u root" in s and "dingo_cluster=main" in s and "checkout" not in s
    )
    assert "sudo" not in build_command(
        ClusterCommand("discover", "test"), "test", "abc", False
    )


class Channel:
    def __init__(self, chunks):
        self.chunks = list(chunks)
        self.sent = []

    def recv_ready(self):
        return False

    def recv(self, n):
        return b""

    def recv_stderr_ready(self):
        return bool(self.chunks)

    def recv_stderr(self, n):
        return self.chunks.pop(0)

    def exit_status_ready(self):
        return not self.chunks

    def recv_exit_status(self):
        return 1

    def sendall(self, x):
        self.sent.append(x)

    def shutdown_write(self):
        pass


def test_only_verified_prompt_requests_password():
    ch = Channel([b"__DTT_AUTH_abc__ro", b"ot__END__"])
    with pytest.raises(AuthenticationRequired) as e:
        read_channel(ch, "abc", None, None, 5, 1024)
    assert e.value.account == "root" and ch.sent == []
    ch = Channel([b"Password:"])
    result = read_channel(ch, "abc", "SECRET", "root", 5, 1024)
    assert ch.sent == [] and result[2] == 1


def test_prompt_account_change_refuses_secret():
    ch = Channel([b"__DTT_AUTH_abc__other__END__"])
    with pytest.raises(Exception):
        read_channel(ch, "abc", "SECRET", "root", 5, 1024)
    assert ch.sent == []


def test_one_secret_send_and_second_prompt_challenge():
    ch = Channel([b"__DTT_AUTH_abc__root__END__", b"__DTT_AUTH_abc__root__END__"])
    with pytest.raises(AuthenticationRequired):
        read_channel(ch, "abc", "SECRET", "root", 5, 1024)
    assert ch.sent == [b"SECRET\n"]


def test_real_loopback_ssh_sudo_stdin_and_framed_result():
    import socket, threading, re
    import paramiko
    from dingofs_platform.inventory.ssh_transport import SSHConfig
    from dingofs_platform.inventory.host_trust import key_info
    from dingofs_platform.clusters.transport import run_session, ClusterCommand

    key = paramiko.RSAKey.generate(2048)
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    listener.settimeout(5)
    received = []
    commands = []
    errors = []

    class Server(paramiko.ServerInterface):
        def check_auth_password(self, user, password):
            return (
                paramiko.AUTH_SUCCESSFUL
                if password == "ssh-test"
                else paramiko.AUTH_FAILED
            )

        def get_allowed_auths(self, user):
            return "password"

        def check_channel_request(self, kind, id):
            return paramiko.OPEN_SUCCEEDED

        def check_channel_exec_request(self, channel, command):
            commands.append(command.decode())
            return True

    def serve():
        connection = None
        try:
            sock, _ = listener.accept()
            connection = paramiko.Transport(sock)
            connection.add_server_key(key)
            connection.start_server(server=Server())
            for i in range(2):
                channel = connection.accept(5)
                channel.settimeout(5)
                import time

                deadline = time.monotonic() + 5
                while len(commands) <= i and time.monotonic() < deadline:
                    time.sleep(0.01)
                command = commands[i]
                if i == 0:
                    channel.send_stderr(b"sudo: a password is required\n")
                    channel.send_exit_status(1)
                else:
                    nonce = re.search(r"__DTT_AUTH_([a-f0-9]+)__%p__END__", command)[1]
                    prompt = f"__DTT_AUTH_{nonce}__ssh-user__END__".encode()
                    channel.send_stderr(prompt[:15])
                    channel.send_stderr(prompt[15:])
                    received.append(channel.recv(1024))
                    channel.send_stderr(
                        f"__DTT_STDERR_{nonce}__\ncommand diagnostic\n".encode()
                    )
                    channel.send(
                        f"login banner\n__DTT_BEGIN_{nonce}__\nroot\n/root\n/bin/dingo\n__DTT_OUTPUT_{nonce}__\nmain-dingofs\n".encode()
                    )
                    channel.send_exit_status(0)
                channel.close()
        except Exception as e:
            errors.append(str(e))
        finally:
            if connection:
                connection.close()
            listener.close()

    thread = threading.Thread(target=serve)
    thread.start()
    try:
        cfg = SSHConfig(
            "127.0.0.1",
            listener.getsockname()[1],
            "ssh-user",
            "ssh-test",
            trusted_host_key=key_info(key),
        )
        result = run_session(
            cfg,
            ClusterCommand("discover", "root"),
            password="switch-test",
            auth_account="ssh-user",
            timeout_s=8,
        )
        assert result.stdout == "main-dingofs\n" and result.identity.user == "root"
        assert result.stderr == "command diagnostic\n"
        assert received == [b"switch-test\n"] and all(
            "switch-test" not in command for command in commands
        )
    finally:
        thread.join(8)
    assert errors == [] and not thread.is_alive()


def stalled_cluster_worker(*args):
    import time

    time.sleep(10)


def test_supervisor_enforces_deadline_and_cleans_child(monkeypatch):
    import time, multiprocessing
    import dingofs_platform.clusters.transport as module

    monkeypatch.setattr(module, "_worker", stalled_cluster_worker)
    before = {p.pid for p in multiprocessing.active_children()}
    start = time.monotonic()
    with pytest.raises(module.ClusterExecutionError, match="timeout"):
        module.execute_cluster(None, ClusterCommand("discover", "root"), timeout_s=0.3)
    assert (
        time.monotonic() - start < 3
        and {p.pid for p in multiprocessing.active_children()} == before
    )
    with pytest.raises(module.ClusterExecutionError, match="cancelled"):
        module.execute_cluster(
            None, ClusterCommand("discover", "root"), cancelled=lambda: True
        )
