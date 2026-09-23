from dataclasses import replace
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock
import pytest, paramiko
from cryptography.fernet import Fernet
from dingofs_platform.inventory.ssh_transport import (
    SSHConfig,
    CollectionError,
    RejectUnknownHost,
    run_session,
)
from dingofs_platform.inventory.models import Machine


@pytest.fixture
def host_key():
    return paramiko.RSAKey.generate(2048)


def info(key, previous=None):
    from dingofs_platform.inventory.host_trust import key_info

    return {**key_info(key), "previous_fingerprint": previous}


def test_unknown_key_is_returned_for_confirmation_before_auth(host_key):
    policy = RejectUnknownHost()
    with pytest.raises(CollectionError) as error:
        policy.missing_host_key(None, "node", host_key)
    assert error.value.code == "host_key_unknown"
    assert error.value.host_key["key_base64"] == host_key.get_base64()
    assert error.value.host_key["fingerprint"].startswith("SHA256:")


def test_missing_known_hosts_allows_safe_fingerprint_discovery(host_key):
    client = MagicMock()
    client.load_host_keys.side_effect = FileNotFoundError()

    def connect(**kwargs):
        policy = client.set_missing_host_key_policy.call_args.args[0]
        policy.missing_host_key(client, "node", host_key)

    client.connect.side_effect = connect
    with pytest.raises(CollectionError) as error:
        run_session(
            SSHConfig("node", 22, "root", "secret", "/absent"),
            {},
            5,
            4096,
            client_factory=lambda: client,
        )
    assert error.value.code == "host_key_unknown"
    assert error.value.host_key["key_base64"] == host_key.get_base64()
    client.get_transport.assert_not_called()


def test_database_pin_has_priority_and_changed_key_contains_both_fingerprints(host_key):
    from dingofs_platform.inventory.host_trust import key_info

    other = paramiko.RSAKey.generate(2048)
    client = MagicMock()
    client.connect.side_effect = paramiko.BadHostKeyException("node", other, host_key)
    config = SSHConfig(
        "node", 2222, "root", "secret", "/absent", trusted_host_key=key_info(host_key)
    )
    with pytest.raises(CollectionError) as error:
        run_session(config, {}, 5, 4096, client_factory=lambda: client)
    assert error.value.code == "host_key_changed"
    assert error.value.host_key["fingerprint"] == key_info(other)["fingerprint"]
    assert (
        error.value.host_key["previous_fingerprint"]
        == key_info(host_key)["fingerprint"]
    )
    client.load_host_keys.assert_not_called()
    assert client.get_host_keys.return_value.add.call_args.args[0] == "[node]:2222"


@pytest.fixture
def machine(admin, app):
    app.state.settings.credential_encryption_key = Fernet.generate_key().decode()
    r = admin.post(
        "/api/v1/machines",
        json=dict(
            name="node", address="node.test", ssh_user="root", ssh_password=" secret "
        ),
    )
    assert r.status_code == 201
    return r.json()


def challenge(admin, app, machine, key):
    def discover(*args, **kwargs):
        raise CollectionError("host_key_unknown", host_key=info(key))

    app.state.hardware_transport = discover
    r = admin.post(
        "/api/v1/machines/" + machine["id"] + "/refresh-hardware",
        json={"base_revision": machine["revision"]},
    )
    assert r.status_code == 200, r.text
    m = r.json()
    assert m["collection_status"] == "needs_trust"
    assert m["ssh_host_trust"]["pending"]["fingerprint"] == info(key)["fingerprint"]
    assert key.get_base64() not in r.text
    return m


def confirm(admin, m, **extra):
    return admin.post(
        "/api/v1/machines/" + m["id"] + "/trust-host-key",
        json=dict(
            base_revision=m["revision"],
            challenge_id=m["ssh_host_trust"]["pending"]["challenge_id"],
            **extra,
        ),
    )


def test_trust_lifecycle_and_replay_rejected(admin, app, machine, host_key):
    m = challenge(admin, app, machine, host_key)
    r = confirm(admin, m)
    assert r.status_code == 200, r.text
    trusted = r.json()
    assert (
        trusted["ssh_host_trust"]["trusted"]["fingerprint"]
        == info(host_key)["fingerprint"]
    )
    assert trusted["ssh_host_trust"]["pending"] is None
    assert confirm(admin, m).status_code == 409
    seen = []

    def capture(config, *a, **k):
        seen.append(config)
        return {}

    app.state.hardware_transport = capture
    admin.post(
        "/api/v1/machines/" + m["id"] + "/refresh-hardware",
        json={"base_revision": trusted["revision"]},
    )
    assert seen[0].trusted_host_key["key_base64"] == host_key.get_base64()
    assert seen[0].password == " secret "


@pytest.mark.parametrize("condition", ["expired", "edited", "archived", "forged"])
def test_stale_or_forged_challenge_is_rejected(
    admin, app, machine, host_key, condition
):
    m = challenge(admin, app, machine, host_key)
    with app.state.session_factory.begin() as db:
        row = db.get(Machine, m["id"])
        if condition == "expired":
            row.ssh_trust_pending = {
                **row.ssh_trust_pending,
                "expires_at": (
                    datetime.now(timezone.utc) - timedelta(seconds=1)
                ).isoformat(),
            }
        elif condition == "edited":
            row.address = "different"
            row.revision += 1
        elif condition == "archived":
            row.archived = True
    if condition == "forged":
        m["ssh_host_trust"]["pending"]["challenge_id"] = "not-server-issued"
    assert confirm(admin, m).status_code == 409
    with app.state.session_factory() as db:
        assert db.get(Machine, m["id"]).ssh_host_key is None


def test_permission_csrf_and_no_arbitrary_key_acceptance(admin, app, machine, host_key):
    m = challenge(admin, app, machine, host_key)
    assert confirm(admin, m, key_base64=host_key.get_base64()).status_code == 422
    del admin.headers["X-CSRF-Token"]
    assert confirm(admin, m).status_code == 403
    r = admin.post(
        "/api/v1/auth/login",
        json={"username": "member", "password": "test-password-123"},
    )
    admin.headers["X-CSRF-Token"] = r.json()["csrf_token"]
    assert confirm(admin, m).status_code == 403


def test_address_change_does_not_reuse_trust(admin, app, machine, host_key):
    m = confirm(admin, challenge(admin, app, machine, host_key)).json()
    r = admin.patch(
        "/api/v1/machines/" + m["id"],
        json={"base_revision": m["revision"], "address": "another.test"},
    )
    assert r.status_code == 200
    m = r.json()
    assert m["ssh_host_trust"]["trusted"] is None
    seen = []
    app.state.hardware_transport = lambda c, *a, **k: seen.append(c) or {}
    admin.post(
        "/api/v1/machines/" + m["id"] + "/refresh-hardware",
        json={"base_revision": m["revision"]},
    )
    assert seen[0].trusted_host_key is None


def test_real_ssh_first_contact_and_key_change_never_send_password(tmp_path):
    import socket, threading, time
    from dingofs_platform.inventory.ssh_transport import execute

    key = paramiko.RSAKey.generate(2048)
    changed = paramiko.RSAKey.generate(2048)
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(3)
    listener.settimeout(6)
    port = listener.getsockname()[1]
    auth = []
    errors = []

    class Server(paramiko.ServerInterface):
        def __init__(self):
            self.ready = threading.Event()

        def check_auth_password(self, username, password):
            auth.append((username, password))
            return paramiko.AUTH_SUCCESSFUL

        def get_allowed_auths(self, username):
            return "password"

        def check_channel_request(self, kind, chanid):
            return paramiko.OPEN_SUCCEEDED

        def check_channel_exec_request(self, channel, command):
            self.ready.set()
            return True

    def serve():
        try:
            for server_key in [key, key, changed]:
                connection, _ = listener.accept()
                transport = paramiko.Transport(connection)
                try:
                    server = Server()
                    transport.add_server_key(server_key)
                    transport.start_server(server=server)
                    channel = transport.accept(2)
                    if channel and server.ready.wait(2):
                        channel.sendall(b"ok\n")
                        channel.send_exit_status(0)
                        channel.shutdown_write()
                        time.sleep(0.05)
                        channel.close()
                except (EOFError, paramiko.SSHException):
                    pass
                finally:
                    transport.close()
        except Exception as exc:
            errors.append(type(exc).__name__)
        finally:
            listener.close()

    worker = threading.Thread(target=serve, daemon=True)
    worker.start()
    config = SSHConfig(
        "127.0.0.1", port, "root", "private-test-password", str(tmp_path / "absent")
    )
    try:
        with pytest.raises(CollectionError) as first:
            execute(config, {"cpu": "lscpu -J"}, timeout_s=5)
        assert first.value.code == "host_key_unknown"
        assert first.value.host_key["key_base64"] == key.get_base64()
        assert auth == []
        trusted = replace(config, trusted_host_key=first.value.host_key)
        assert (
            execute(trusted, {"cpu": "lscpu -J"}, timeout_s=5)["cpu"].stdout == "ok\n"
        )
        assert len(auth) == 1
        with pytest.raises(CollectionError) as last:
            execute(trusted, {"cpu": "lscpu -J"}, timeout_s=5)
        assert last.value.code == "host_key_changed"
        assert last.value.host_key["fingerprint"] == info(changed)["fingerprint"]
        assert last.value.host_key["previous_fingerprint"] == info(key)["fingerprint"]
        assert len(auth) == 1
    finally:
        listener.close()
        worker.join(7)
    assert not worker.is_alive() and not errors
