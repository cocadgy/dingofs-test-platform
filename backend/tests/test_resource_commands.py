import json
import os
import shlex

import pytest


def api():
    from dingofs_platform.resources import commands

    return commands


def request(action, parameters, record=None):
    parts = shlex.split(
        api().build_script(action, parameters, "10.0.0.1:7400", "resource-1", record)
    )
    assert parts[:2] == ["python3", "-c"]
    compile(parts[2], "remote_helper", "exec")
    return json.loads(parts[3])


def test_catalog_contains_requested_operations_and_secret_fields():
    actions = {row["action"]: row for row in api().catalog()}
    assert len(actions) == 33
    assert actions["mount.delete"]["mutating"] is True
    assert {"cache.leave", "cache.unlock", "cache.weight"} <= actions.keys()
    assert actions["cache.create"]["mutating"] is True
    assert actions["mount.logs"]["mutating"] is False
    assert actions["mount.remount"]["mutating"] is True
    assert api().secret_keys("fs.create") == {"s3_ak", "s3_sk", "rados_key"}
    assert actions["fs.create"]["fields"]


@pytest.mark.parametrize(
    "action,values",
    [
        ("fs.list", {"shell": "id"}),
        ("fs.create", {"fs_name": "bad/name", "storage_type": "s3"}),
        ("quota.fs.set", {"fs_name": "data", "capacity": -1, "inodes": 3}),
        ("dirstat.info", {"fs_id": True, "path": "/"}),
        ("mount.logs", {"resource_id": "abc", "filename": "../outside"}),
        ("mount.logs", {"resource_id": "abc", "lines": 1001}),
        ("mount.unmount", {"resource_id": "abc", "mount_path": "/etc"}),
        ("cache.stop", {"resource_id": "abc", "pid": 4}),
        ("dirstat.info", {"fs_id": 2, "path": "/", "mds_client_path": "x; id"}),
    ],
)
def test_untrusted_parameters_are_rejected(action, values):
    with pytest.raises(ValueError):
        api().validate(action, values)


def test_s3_defaults_and_command_keep_credentials_as_single_arguments():
    values = api().validate(
        "fs.create",
        {
            "fs_name": "data",
            "storage_type": "s3",
            "s3_ak": "key",
            "s3_sk": "secret ' $(touch /tmp/never)",
            "s3_endpoint": "http://s3:9000",
            "s3_bucketname": "data",
        },
    )
    assert values["partition_type"] == "hash"
    argv = request("fs.create", values)["commands"][0]
    assert argv[:4] == ["dingo", "fs", "create", "data"]
    assert argv[argv.index("--s3.sk") + 1] == values["s3_sk"]
    assert argv[-2:] == ["--format", "json"]


def test_rdma_requires_device_and_port_and_maps_actual_flags():
    mount = {
        "machine_id": "machine-1",
        "target_user": "dingofs",
        "fs_name": "data",
        "mount_path": "/mnt/data",
        "use_rdma": True,
    }
    with pytest.raises(ValueError):
        api().validate("mount.create", mount)
    mount.update(rdma_device="mlx5_0", rdma_port=1)
    values = api().validate("mount.create", mount)
    record = dict(
        values,
        state_dir="/tmp/dingofs-platform-resources/cluster/resource",
        log_dir="/tmp/dingofs-platform-resources/cluster/resource/logs",
    )
    req = request("mount.create", values, record)
    from dingofs_platform.resources.remote_helper import mount_argv

    argv = mount_argv(req)
    assert "--use_rdma=true" in argv
    assert "--cache_rdma_device=mlx5_0" in argv
    assert "--cache_rdma_port_num=1" in argv
    assert "--log_dir=" + record["log_dir"] in argv


def test_cache_create_normalizes_member_list_and_rejects_duplicate_endpoint():
    member = {
        "machine_id": "m1",
        "target_user": "dingofs",
        "listen_ip": "10.1.1.1",
        "listen_port": 9300,
        "cache_dir": "/mnt/cache",
        "cache_size_mb": 1024,
        "use_rdma": False,
    }
    value = api().validate(
        "cache.create", {"group_name": "group-1", "members": [member]}
    )
    assert value["cache_expire_s"] == 259200
    assert value["members"][0]["rdma_device"] == ""
    with pytest.raises(ValueError):
        api().validate(
            "cache.create", {"group_name": "group-1", "members": [member, member]}
        )


def test_fixed_quota_trash_and_dirstat_commands():
    assert request("quota.fs.delete", {"fs_name": "data"})["commands"][0][2:5] == [
        "config",
        "set",
        "--fsname",
    ]
    argv = request(
        "dirstat.sync", {"fs_id": 5, "path": "/data", "recursive": True, "repair": True}
    )["commands"][0]
    assert "--recursive" in argv and "--repair" in argv
    assert argv[0] == "dingo-mds-client"
    argv = request("trash.restore", {"fs_id": 5})["commands"][0]
    assert "--put_back=true" in argv
    assert "--cmd=restoretrash" in argv


def test_mount_lifecycle_requires_server_record():
    with pytest.raises(ValueError):
        request("mount.logs", {"resource_id": "abc"})
    with pytest.raises(ValueError):
        request("cache.stop", {"resource_id": "abc"})


def test_client_logs_are_bounded_and_refuse_symlinks(tmp_path):
    from dingofs_platform.resources.remote_helper import read_logs

    logs = tmp_path / "logs"
    logs.mkdir()
    (logs / "client.log").write_text("old\nlatest\n")
    (logs / "escape").symlink_to("/etc/passwd")
    req = {
        "record": {"log_dir": str(logs)},
        "parameters": {"filename": "client.log", "lines": 1},
    }
    assert read_logs(req)["text"] == "latest\n"
    req["parameters"]["filename"] = "escape"
    with pytest.raises((ValueError, OSError)):
        read_logs(req)
    req["parameters"]["filename"] = "../outside"
    with pytest.raises(ValueError):
        read_logs(req)


def test_owned_state_refuses_symlink_or_existing_unowned_directory(tmp_path):
    from dingofs_platform.resources.remote_helper import OwnedState

    target = tmp_path / "target"
    target.mkdir()
    (tmp_path / "link").symlink_to(target, target_is_directory=True)
    with pytest.raises((ValueError, OSError)):
        OwnedState(str(tmp_path / "link"), "mine", create=True)
    with pytest.raises(ValueError):
        OwnedState(str(target), "mine", create=True)


def test_signal_fails_closed_on_process_identity_mismatch(monkeypatch):
    from dingofs_platform.resources import remote_helper

    called = []
    monkeypatch.setattr(
        remote_helper,
        "process_identity",
        lambda pid: {
            "pid": pid,
            "start_ticks": "different",
            "exe": "/opt/dingo-cache",
            "argv": [],
        },
    )
    monkeypatch.setattr(os, "pidfd_open", lambda pid: called.append(pid), raising=False)
    with pytest.raises(ValueError):
        remote_helper.stop_recorded_process(
            {
                "pid": 123,
                "start_ticks": "original",
                "exe": "/opt/dingo-cache",
                "argv": [],
            }
        )
    assert called == []


def test_both_json_error_envelopes_are_rejected():
    from dingofs_platform.resources.remote_helper import check_json

    with pytest.raises(ValueError):
        check_json({"error": {"code": 1, "description": "transport"}})
    with pytest.raises(ValueError):
        check_json(
            {
                "error": {"code": 0},
                "result": {"error": {"errcode": 3, "errmsg": "business"}},
            }
        )
    assert (
        check_json({"error": {"code": 0}, "result": {"members": []}})["result"][
            "members"
        ]
        == []
    )


def test_catalog_uses_frontend_types_and_sections():
    for row in api().catalog():
        assert row["section"] in {"filesystem", "cache", "mount"}
        for field in row["fields"]:
            assert field["type"] in {
                "text",
                "number",
                "select",
                "boolean",
                "password",
                "members",
                "names",
                "cache_options", "mount_options",
            }


def test_log_line_select_normalizes_decimal_string():
    assert (
        api().validate("mount.logs", {"resource_id": "test", "lines": "100"})["lines"]
        == 100
    )


def test_existing_cache_group_accepts_new_member_but_rejects_endpoint_collision(monkeypatch):
    from dingofs_platform.resources import remote_helper
    members = [{"member_id": "external", "group_name": "existing", "ip": "192.0.2.1", "port": 21000}]
    monkeypatch.setattr(remote_helper, "member_list", lambda req: members)
    req = {"action": "cache.create", "record": {"member_id": "new", "group_name": "existing", "listen_ip": "192.0.2.1", "listen_port": 21001}}
    remote_helper.check_group_available(req)
    req["record"]["listen_port"] = 21000
    with pytest.raises(ValueError, match="endpoint"):
        remote_helper.check_group_available(req)
    req["action"] = "cache.stop"
    remote_helper.check_group_available(req)


def test_private_state_round_trip_and_identity_mismatch(tmp_path):
    from dingofs_platform.resources.remote_helper import OwnedState

    path = str(tmp_path / "private")
    with OwnedState(path, "one", create=True) as store:
        store.save({"state": "stopped"})
    with OwnedState(path, "one") as store:
        assert store.load() == {"state": "stopped"}
    with pytest.raises(ValueError):
        OwnedState(path, "different")


def test_nonzero_business_response_fails_even_with_successful_process():
    import sys

    from dingofs_platform.resources.remote_helper import run_command

    code = 'print(\'{"error":{"code":0},"result":{"error":{"errcode":7,"errmsg":"denied"}}}\')'
    with pytest.raises(ValueError, match="denied"):
        run_command([sys.executable, "-c", code], require_json=True)


def test_redaction_covers_nested_storage_details_and_text():
    from dingofs_platform.resources.remote_helper import redact

    value = {
        "result": {
            "fs_infos": [
                {
                    "s3Info": {
                        "accessKey": "access-value",
                        "secretKey": "secret-value",
                    },
                    "radosInfo": {"key": "rados-secret"},
                }
            ]
        },
        "stdout": 'header\n"key": "rados-secret"\nsecret_key=unquoted-secret\n',
    }
    result = json.dumps(redact(value))
    for secret in ("rados-secret", "unquoted-secret", "access-value", "secret-value"):
        assert secret not in result


def test_invalid_member_list_is_not_treated_as_deleted(monkeypatch):
    from dingofs_platform.resources import remote_helper

    monkeypatch.setattr(
        remote_helper, "run_command", lambda *args, **kwargs: {"result": {"other": []}}
    )
    with pytest.raises(ValueError, match="member list"):
        remote_helper._membership(
            {"mds_addr": "localhost:7400", "record": {"member_id": "owned"}}
        )


def test_command_output_limit_stops_producer():
    import sys

    from dingofs_platform.resources.remote_helper import run_command

    with pytest.raises(ValueError, match="output exceeded"):
        run_command(
            [
                sys.executable,
                "-c",
                "import os,time; os.write(1, b'x' * 2000000); time.sleep(10)",
            ],
            timeout=2,
        )


def test_command_timeout_stops_descendants(tmp_path):
    import sys
    import time

    from dingofs_platform.resources.remote_helper import run_command

    marker = tmp_path / "must-not-exist"
    child = (
        f"import time,pathlib; time.sleep(0.5); pathlib.Path({str(marker)!r}).touch()"
    )
    parent = f"import subprocess,sys,time; subprocess.Popen([sys.executable,'-c',{child!r}]); time.sleep(10)"
    with pytest.raises(ValueError, match="timed out"):
        run_command([sys.executable, "-c", parent], timeout=0.1)
    time.sleep(0.6)
    assert not marker.exists()


def test_replaced_mount_refuses_old_record_unmount(monkeypatch):
    from dingofs_platform.resources import remote_helper as helper

    process = {
        "pid": 1234,
        "start_ticks": "old",
        "exe": "/bin/dingo-client",
        "argv": ["dingo-client", "/mnt/owned"],
    }
    old_mount = {"mount_id": "12", "mount_path": "/mnt/owned"}

    class Store:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def load(self):
            return {"process": process, "mount": old_mount}

    monkeypatch.setattr(helper, "OwnedState", lambda *args, **kwargs: Store())
    monkeypatch.setattr(helper, "process_identity", lambda pid: process)
    monkeypatch.setattr(
        helper,
        "mount_identity",
        lambda path: {"mount_id": "99", "mount_path": path},
        raising=False,
    )
    monkeypatch.setattr(helper, "mounted", lambda path: True)
    monkeypatch.setattr(
        helper,
        "run_command",
        lambda *args, **kwargs: pytest.fail("must not unmount replacement"),
    )
    with pytest.raises(ValueError, match="mount identity"):
        helper.lifecycle(
            {
                "action": "mount.unmount",
                "resource_id": "owned",
                "record": {"state_dir": "/tmp/owned", "mount_path": "/mnt/owned"},
            }
        )


def test_missing_state_cache_member_can_be_deleted_only_when_absent(monkeypatch):
    from dingofs_platform.resources import remote_helper as helper

    def absent_state(*args, **kwargs):
        raise FileNotFoundError("not started")

    monkeypatch.setattr(helper, "OwnedState", absent_state)
    monkeypatch.setattr(helper, "check_group_available", lambda req: None)
    monkeypatch.setattr(helper, "find_process", lambda req: None)
    monkeypatch.setattr(helper, "_membership", lambda req: None)
    state, _data = helper.lifecycle(
        {
            "action": "cache.delete",
            "resource_id": "group",
            "record": {"state_dir": "/tmp/missing", "member_id": "never-started"},
        }
    )
    assert state == "deleted"
    monkeypatch.setattr(
        helper, "_membership", lambda req: {"member_id": "never-started"}
    )
    with pytest.raises(ValueError, match="ownership"):
        helper.lifecycle(
            {
                "action": "cache.delete",
                "resource_id": "group",
                "record": {"state_dir": "/tmp/missing", "member_id": "never-started"},
            }
        )


def test_interrupted_cache_start_recovers_unique_owned_process(monkeypatch):
    from dingofs_platform.resources import remote_helper as helper

    process = {
        "pid": 1234,
        "start_ticks": "42",
        "exe": "/bin/dingo-cache",
        "argv": ["dingo-cache", "--id=owned"],
    }
    persisted = {"launch_started": True}

    class Store:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def load(self):
            return dict(persisted)

        def save(self, state):
            persisted.update(state)

    monkeypatch.setattr(helper, "OwnedState", lambda *args, **kwargs: Store())
    monkeypatch.setattr(helper, "check_group_available", lambda req: None)
    monkeypatch.setattr(helper, "find_process", lambda req: process)
    monkeypatch.setattr(helper, "process_identity", lambda pid: process)
    monkeypatch.setattr(helper, "_membership", lambda req: None)
    signals = []
    monkeypatch.setattr(
        helper, "stop_recorded_process", lambda row: signals.append(row)
    )
    state, _ = helper.lifecycle(
        {
            "action": "cache.stop",
            "resource_id": "group",
            "record": {"state_dir": "/tmp/owned", "member_id": "owned"},
        }
    )
    assert state == "stopped"
    assert persisted["process"] == process
    assert signals == [process]


def test_cache_data_path_rejects_dingo_multidisk_syntax():
    values = {
        "group_name": "g",
        "members": [
            {
                "machine_id": "m",
                "listen_ip": "10.0.0.1",
                "cache_dir": "/mnt/data,/tmp/other",
            }
        ],
    }
    with pytest.raises(ValueError):
        api().validate("cache.create", values)


def test_mount_paths_are_canonicalized():
    values = api().validate(
        "mount.create",
        {"machine_id": "m", "fs_name": "data", "mount_path": "/mnt/data/"},
    )
    assert values["mount_path"] == "/mnt/data"


def test_cache_expiry_is_not_advertised_or_sent_to_cli():
    from dingofs_platform.resources.remote_helper import cache_argv

    create = next(row for row in api().catalog() if row["action"] == "cache.create")
    assert "cache_expire_s" not in {f["key"] for f in create["fields"]}
    record = {
        "member_id": "m",
        "group_name": "g",
        "listen_ip": "10.0.0.1",
        "listen_port": 21000,
        "cache_dir": "/mnt/cache/m",
        "cache_size_mb": 1024,
        "log_dir": "/tmp/logs",
    }
    assert not any(
        "cache_expire_s" in arg
        for arg in cache_argv({"record": record, "mds_addr": "10.0.0.1:7400"})
    )


def test_mds_reason_is_preserved_when_cli_envelope_also_fails():
    from dingofs_platform.resources.remote_helper import check_json

    with pytest.raises(ValueError) as error:
        check_json(
            {
                "error": {
                    "code": 1,
                    "description": "rpc request to mds cluster failed",
                },
                "result": {
                    "error": {"errcode": "EEXISTED", "errmsg": "fs exist mount point."}
                },
            }
        )
    assert "EEXISTED" in str(error.value)
    assert "fs exist mount point." in str(error.value)
    assert "rpc request to mds cluster failed" in str(error.value)


def test_nonzero_cli_exit_preserves_json_business_error():
    import sys

    from dingofs_platform.resources.remote_helper import run_command

    script = 'import json,sys; print(json.dumps({"error":{"code":1,"description":"rpc failed"},"result":{"error":{"errcode":"EEXISTED","errmsg":"fs exist mount point."}}})); print("diagnostic stderr",file=sys.stderr); sys.exit(1)'
    with pytest.raises(ValueError) as error:
        run_command([sys.executable, "-c", script], require_json=True)
    assert "EEXISTED" in str(error.value)
    assert "fs exist mount point." in str(error.value)
    assert "diagnostic stderr" in str(error.value)


def test_generic_rpc_failure_does_not_invent_a_business_reason():
    from dingofs_platform.resources.remote_helper import check_json

    with pytest.raises(ValueError) as error:
        check_json(
            {"error": {"code": 1, "description": "rpc request to mds cluster failed"}}
        )
    assert "rpc request to mds cluster failed" in str(error.value)
    assert "mount point" not in str(error.value)


@pytest.mark.parametrize("action", ["fs.get", "trash.get"])
def test_fs_query_uses_json_response_without_verbose_request(action):
    argv = request(action, {"fs_name": "test2"})["commands"][0]
    assert argv == [
        "dingo", "fs", "query", "--fsname", "test2", "--mdsaddr",
        "10.0.0.1:7400", "--format", "json",
    ]
    assert "--verbose" not in argv


@pytest.mark.parametrize("names", [[], ["a", "a"], [""], ["bad;name"], ["a"] * 101, "test.*"])
def test_batch_rejects_invalid_names(names):
    from dingofs_platform.resources.schemas import validate
    with pytest.raises(ValueError):
        validate("fs.delete_batch", {"fs_names": names})


def test_batch_prepares_exact_snapshot(monkeypatch):
    from dingofs_platform.resources import service
    monkeypatch.setattr(service, "step", lambda db, actor, c, action, p: (action, p))
    steps, resource = service.prepare(None, None, None, "fs.delete_batch", {"fs_names": ["test-a", "test-b"]})
    assert steps == [("fs.delete", {"fs_name": "test-a"}), ("fs.delete", {"fs_name": "test-b"})]
    assert resource is None


def test_remount_uses_saved_resource_record_without_new_parameters():
    values = api().validate("mount.remount", {"resource_id": "resource-1"})
    record = {"state_dir": "/tmp/state", "log_dir": "/tmp/logs",
              "fs_name": "data", "mount_path": "/mnt/data",
              "mount_options": {"block_size": "4096"}}
    req = request("mount.remount", values, record)
    assert req["record"] == record
    assert req["parameters"] == values


def test_mds_client_uses_utc_hour_buckets_and_accepts_explicit_range():
    from datetime import datetime, timezone
    from dingofs_platform.resources.commands import recent_hour_buckets
    now = datetime(2026, 10, 13, 2, 15, tzinfo=timezone.utc)
    assert recent_hour_buckets(1, now) == '2026-10-13-01,2026-10-13-02'
    req = request('trash.restore', {'fs_id': 5, 'restore_hours_utc': '2026-10-13-01,2026-10-13-02'})
    assert '--hours=2026-10-13-01,2026-10-13-02' in req['commands'][0]
    with pytest.raises(ValueError):
        api().validate('trash.restore', {'fs_id': 5, 'restore_hours_utc': 'yesterday; id'})


def test_mds_client_resolves_installed_binary_and_single_reachable_endpoint(tmp_path, monkeypatch):
    from dingofs_platform.resources.remote_helper import prepare_mds_command
    root = tmp_path / '.dingo/components/dingo-mds-client/main'
    root.mkdir(parents=True)
    binary = root / 'dingo-mds-client'
    binary.write_text('#!/bin/sh\nexit 0\n')
    binary.chmod(0o755)
    monkeypatch.setattr('dingofs_platform.resources.remote_helper.shutil.which', lambda name: None)
    seen = []
    class Connection:
        def __enter__(self): return self
        def __exit__(self, *args): pass
    def connect(address, timeout):
        seen.append(address)
        if address[1] == 6900: raise OSError('offline')
        return Connection()
    monkeypatch.setattr('dingofs_platform.resources.remote_helper.socket.create_connection', connect)
    req = {'action': 'dirstat.info', 'mds_addr': '10.0.0.1:6900,10.0.0.2:6901',
           'tool_home': str(tmp_path)}
    argv = prepare_mds_command(req, ['dingo-mds-client', '--mds_addr='+req['mds_addr'], '--cmd=info'])
    assert argv == [str(binary), '--mds_addr=10.0.0.2:6901', '--cmd=info']
    assert seen == [('10.0.0.1', 6900), ('10.0.0.2', 6901)]


def test_mds_cli_failure_text_fails_even_with_zero_exit():
    import sys
    from dingofs_platform.resources.remote_helper import CommandFailure, run_command
    with pytest.raises(CommandFailure, match='only root can restore'):
        run_command([sys.executable, '-c', 'print("only root can restore files from trash")'])
    with pytest.raises(CommandFailure, match='failed'):
        run_command([sys.executable, '-c', 'print("✗ updatefstrashdays failed: invalid address")'])


def test_dirstat_read_uses_next_mds_when_first_path_lookup_is_empty(tmp_path, monkeypatch):
    from dingofs_platform.resources.remote_helper import run_mds_command
    binary = tmp_path / 'dingo-mds-client'
    binary.write_text('#!/bin/sh\nexit 0\n')
    binary.chmod(0o755)
    class Connection:
        def __enter__(self): return self
        def __exit__(self, *args): pass
    monkeypatch.setattr('dingofs_platform.resources.remote_helper.socket.create_connection',
                        lambda *args, **kwargs: Connection())
    seen = []
    def execute(argv, **kwargs):
        seen.append(argv)
        return {'stdout': '' if '--mds_addr=10.0.0.1:6900' in argv else '/new :\n  files: 2\n',
                'stderr': '', 'returncode': 0}
    monkeypatch.setattr('dingofs_platform.resources.remote_helper.run_command', execute)
    req = {'action': 'dirstat.info', 'mds_addr': '10.0.0.1:6900,10.0.0.2:6901',
           'parameters': {'path': '/new'}}
    value = run_mds_command(req, [str(binary), '--mds_addr='+req['mds_addr'],
                                  '--cmd=info', '--fs_id=5', '--path=/new'])
    assert value['stdout'] == '/new :\n  files: 2\n'
    assert [next(arg for arg in call if arg.startswith('--mds_addr=')) for call in seen] == [
        '--mds_addr=10.0.0.1:6900', '--mds_addr=10.0.0.2:6901']


def test_dirstat_read_rejects_empty_results_from_every_mds(tmp_path, monkeypatch):
    from dingofs_platform.resources.remote_helper import CommandFailure, run_mds_command
    binary = tmp_path / 'dingo-mds-client'
    binary.write_text('#!/bin/sh\nexit 0\n')
    binary.chmod(0o755)
    class Connection:
        def __enter__(self): return self
        def __exit__(self, *args): pass
    monkeypatch.setattr('dingofs_platform.resources.remote_helper.socket.create_connection',
                        lambda *args, **kwargs: Connection())
    monkeypatch.setattr('dingofs_platform.resources.remote_helper.run_command',
                        lambda *args, **kwargs: {'stdout': '', 'stderr': '', 'returncode': 0})
    req = {'action': 'dirstat.summary', 'mds_addr': '10.0.0.1:6900,10.0.0.2:6901',
           'parameters': {'path': '/new'}}
    with pytest.raises(CommandFailure, match='目录路径'):
        run_mds_command(req, [str(binary), '--mds_addr='+req['mds_addr'],
                              '--cmd=summary', '--fs_id=5', '--path=/new'])


def test_dirstat_sync_probes_path_and_runs_mutation_once(tmp_path, monkeypatch):
    from dingofs_platform.resources.remote_helper import run_mds_command
    binary = tmp_path / 'dingo-mds-client'
    binary.write_text('#!/bin/sh\nexit 0\n')
    binary.chmod(0o755)
    class Connection:
        def __enter__(self): return self
        def __exit__(self, *args): pass
    monkeypatch.setattr('dingofs_platform.resources.remote_helper.socket.create_connection',
                        lambda *args, **kwargs: Connection())
    seen = []
    def execute(argv, **kwargs):
        seen.append(argv)
        if '--cmd=info' in argv:
            return {'stdout': '' if '--mds_addr=10.0.0.1:6900' in argv else '/new :\n  files: 2\n',
                    'stderr': '', 'returncode': 0}
        return {'stdout': 'all dir-stats are consistent\n', 'stderr': '', 'returncode': 0}
    monkeypatch.setattr('dingofs_platform.resources.remote_helper.run_command', execute)
    req = {'action': 'dirstat.sync', 'mds_addr': '10.0.0.1:6900,10.0.0.2:6901',
           'parameters': {'path': '/new'}}
    value = run_mds_command(req, [str(binary), '--mds_addr='+req['mds_addr'],
                                  '--cmd=syncdirstat', '--fs_id=5', '--path=/new', '--recursive', '--repair'])
    assert value['stdout'] == 'all dir-stats are consistent\n'
    mutations = [call for call in seen if '--cmd=syncdirstat' in call]
    assert len(mutations) == 1
    assert '--mds_addr=10.0.0.2:6901' in mutations[0]


def test_dirstat_read_surfaces_cli_path_error_when_every_mds_fails(tmp_path, monkeypatch):
    from dingofs_platform.resources.remote_helper import CommandFailure, run_mds_command
    binary = tmp_path / 'dingo-mds-client'
    binary.write_text('#!/bin/sh\nexit 0\n')
    binary.chmod(0o755)
    class Connection:
        def __enter__(self): return self
        def __exit__(self, *args): pass
    monkeypatch.setattr('dingofs_platform.resources.remote_helper.socket.create_connection',
                        lambda *args, **kwargs: Connection())
    def execute(argv, **kwargs):
        raise CommandFailure("command failed (exit 1): resolve path '/missing': not found dentry")
    monkeypatch.setattr('dingofs_platform.resources.remote_helper.run_command', execute)
    req = {'action': 'dirstat.info', 'mds_addr': '10.0.0.1:6900,10.0.0.2:6901',
           'parameters': {'path': '/missing'}}
    with pytest.raises(CommandFailure, match='not found dentry'):
        run_mds_command(req, [str(binary), '--mds_addr='+req['mds_addr'],
                              '--cmd=info', '--fs_id=5', '--path=/missing'])
