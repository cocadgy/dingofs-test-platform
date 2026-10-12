"""HTTP -> supervised SSH -> real log helper, using only loopback and temp files."""

import json
import shlex
import socket
import subprocess
import threading
import time

import paramiko
import pytest
from conftest import register_cluster
from cryptography.fernet import Fernet
from dingofs_platform.audit.models import AuditEvent
from dingofs_platform.inventory.host_trust import key_info
from dingofs_platform.inventory.models import Cluster, Machine
from dingofs_platform.remote.models import RemoteSession
from sqlalchemy import select


@pytest.fixture
def local_logs_ssh(tmp_path):
    root = tmp_path / "logs"
    root.mkdir()
    key = paramiko.RSAKey.generate(2048)
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(8)
    listener.settimeout(0.2)
    stopped = threading.Event()
    connections = []
    commands = []
    failures = []

    class Server(paramiko.ServerInterface):
        def __init__(self):
            self.command = None
            self.requested = threading.Event()

        def check_auth_password(self, username, password):
            return (
                paramiko.AUTH_SUCCESSFUL
                if (username, password) == ("test", "test-secret")
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
            self.command = command.decode()
            self.requested.set()
            return True

    def serve(connection):
        transport = paramiko.Transport(connection)
        try:
            server = Server()
            transport.add_server_key(key)
            transport.start_server(server=server)
            channel = transport.accept(5)
            if channel is None or not server.requested.wait(5):
                return
            argv = shlex.split(server.command)
            assert argv[:3] == ["exec", "python3", "-c"]
            assert len(argv) == 5
            parameters = json.loads(argv[-1])
            assert parameters["root"] == str(root)
            assert parameters["kind"] in {"files", "read", "download"}
            commands.append(parameters)
            # Only the fixed helper is executed. No local shell or SSH daemon.
            result = subprocess.run(
                argv[1:], capture_output=True, timeout=5, check=False
            )
            if result.stdout:
                channel.sendall(result.stdout)
            if result.stderr:
                channel.sendall_stderr(result.stderr)
            channel.send_exit_status(result.returncode)
            deadline = time.monotonic() + 3
            while (
                not channel.closed
                and not stopped.is_set()
                and time.monotonic() < deadline
            ):
                time.sleep(0.01)
        except (OSError, EOFError, paramiko.SSHException):
            pass  # A rejected host key disconnects before authentication.
        except (AssertionError, ValueError, subprocess.TimeoutExpired) as exc:
            failures.append(exc)
        finally:
            transport.close()

    def accept():
        while not stopped.is_set():
            try:
                connection, _ = listener.accept()
            except TimeoutError:
                continue
            except OSError:
                return
            thread = threading.Thread(target=serve, args=(connection,), daemon=True)
            connections.append(thread)
            thread.start()

    accepting = threading.Thread(target=accept, daemon=True)
    accepting.start()
    try:
        yield {
            "root": root,
            "port": listener.getsockname()[1],
            "key": key_info(key),
            "commands": commands,
        }
    finally:
        stopped.set()
        listener.close()
        accepting.join(2)
        for thread in connections:
            thread.join(6)
            assert not thread.is_alive()
        assert not accepting.is_alive()
        assert not failures, failures


def register_loopback_target(admin, endpoint):
    settings = admin.app.state.settings
    settings.credential_encryption_key = Fernet.generate_key().decode()
    response = admin.post(
        "/api/v1/machines",
        json={
            "name": "loopback-logs",
            "address": "127.0.0.1",
            "ssh_port": endpoint["port"],
            "ssh_user": "test",
            "ssh_password": "test-secret",
        },
    )
    assert response.status_code == 201, response.text
    machine = response.json()
    cluster = register_cluster(admin, machine)
    with admin.app.state.session_factory.begin() as db:
        row = db.get(Machine, machine["id"])
        assert row.ssh_password_ciphertext != "test-secret"
        row.ssh_host_key = {
            **endpoint["key"],
            "host": "127.0.0.1",
            "port": endpoint["port"],
        }
        db.get(Cluster, cluster["id"]).status_snapshot = {
            "services": [
                {
                    "id": "logs-e2e",
                    "host": "127.0.0.1",
                    "role": "mds",
                    "log_dir": str(endpoint["root"]),
                }
            ]
        }
    assert not hasattr(admin.app.state, "remote_job_factory")
    return machine, cluster


def create_log_session(admin, cluster, kind, **kwargs):
    response = admin.post(
        "/api/v1/remote-sessions",
        json={
            "cluster_id": cluster["id"],
            "service_id": "logs-e2e",
            "kind": kind,
            **kwargs,
        },
    )
    assert response.status_code == 202, response.text
    sid = response.json()["id"]
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        result = admin.get("/api/v1/remote-sessions/" + sid)
        assert result.status_code == 200, result.text
        view = result.json()
        if view["state"] not in {"pending", "connecting", "ready", "running"}:
            return view
        time.sleep(0.02)
    pytest.fail("Remote HTTP session did not finish: " + str(view))


def test_http_list_read_download_through_real_ssh_worker(admin, local_logs_ssh):
    endpoint = local_logs_ssh
    name = "mds '$(id).INFO"
    content = b"private-log-sentinel\n\x1b[31mred\x1b[0m\xff\n"
    (endpoint["root"] / name).write_bytes(content)
    (endpoint["root"] / "latest").symlink_to(name)
    _, cluster = register_loopback_target(admin, endpoint)

    listing = create_log_session(admin, cluster, "files")
    assert listing["state"] == "succeeded", listing
    files = {entry["name"]: entry for entry in listing["result"]["files"]}
    assert set(files) == {name, "latest"}
    assert files[name]["size"] == len(content)
    fid = files[name]["file_id"]
    read = create_log_session(admin, cluster, "read", file_id=fid, lines=100)
    assert read["state"] == "succeeded", read
    assert read["result"]["text"] == "private-log-sentinel\nred\ufffd\n"
    assert read["result"]["cursor"]["offset"] == len(content)

    download = create_log_session(admin, cluster, "download", file_id=fid)
    assert download["state"] == "succeeded", download
    response = admin.get("/api/v1/remote-sessions/" + download["id"] + "/download")
    assert response.status_code == 200, response.text
    assert response.content == content
    assert int(response.headers["content-length"]) == len(content)
    assert response.headers["cache-control"] == "no-store"
    assert [item["kind"] for item in endpoint["commands"]] == [
        "files",
        "read",
        "download",
    ]

    with admin.app.state.session_factory() as db:
        assert db.get(RemoteSession, read["id"]).result is None
        persisted = [row.result for row in db.scalars(select(RemoteSession))]
        persisted += [row.detail for row in db.scalars(select(AuditEvent))]
        assert "private-log-sentinel" not in json.dumps(persisted)
        assert "test-secret" not in json.dumps(persisted)


def test_http_read_revalidates_symlink_after_listing(admin, local_logs_ssh):
    endpoint = local_logs_ssh
    root = endpoint["root"]
    (root / "app").write_text("allowed")
    (root.parent / "secret").write_text("outside-sentinel")
    latest = root / "latest"
    latest.symlink_to("app")
    _, cluster = register_loopback_target(admin, endpoint)
    listing = create_log_session(admin, cluster, "files")
    assert listing["state"] == "succeeded", listing
    fid = next(
        item["file_id"]
        for item in listing["result"]["files"]
        if item["name"] == "latest"
    )
    latest.unlink()
    latest.symlink_to("../secret")
    read = create_log_session(admin, cluster, "read", file_id=fid)
    assert read["state"] == "failed", read
    assert read["error_code"] == "path_escape"
    assert read["result"] is None
    assert "outside-sentinel" not in json.dumps(read)
