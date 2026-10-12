"""Compatibility with sudo -i command re-quoting and current-cluster markers."""

import os
import pwd
import shlex
import subprocess
import pytest
from dingofs_platform.clusters.transport import ClusterCommand, build_command
from dingofs_platform.clusters.parser import parse_cluster_names, ClusterParseError


@pytest.mark.parametrize(
    "kind", ["discover", "status", "topology", "start", "stop", "restart"]
)
def test_sudo_login_script_has_explicit_separators(kind):
    command = ClusterCommand(
        kind,
        "root",
        None if kind == "discover" else "main",
        scope="all" if kind in {"start", "stop", "restart"} else None,
    )
    script = shlex.split(build_command(command, "sunjj", "probe", False))[-1]
    # sudo -i re-quotes the command through the login shell: literal newlines
    # may become whitespace, so every top-level command needs an explicit ';'.
    assert "\n" not in script
    assert "|| exit 92;" in script
    assert "|| exit 91;" in script


def test_login_script_emits_identity_before_discovery(tmp_path):
    user = pwd.getpwuid(os.geteuid()).pw_name
    binary = tmp_path / "dingo"
    binary.write_text('#!/bin/sh\nprintf "* main-dingofs\\n  test-dingofs\\n"\n')
    binary.chmod(0o755)
    command = build_command(
        ClusterCommand("discover", user), "other-user", "probe", False
    )
    script = shlex.split(command)[-1]
    result = subprocess.run(
        ["sh", "-c", script],
        capture_output=True,
        text=True,
        env={**os.environ, "PATH": str(tmp_path) + ":" + os.environ["PATH"]},
        check=True,
    )
    assert result.stdout.startswith("__DTT_BEGIN_probe__\n" + user + "\n")
    assert "__DTT_STDERR_probe__\n" in result.stderr
    output = result.stdout.split("__DTT_OUTPUT_probe__\n", 1)[1]
    assert parse_cluster_names(output) == ["main-dingofs", "test-dingofs"]


def test_failed_identity_never_executes_dingo(tmp_path):
    binary = tmp_path / "dingo"
    binary.write_text("#!/bin/sh\necho should-not-execute\n")
    binary.chmod(0o755)
    script = shlex.split(
        build_command(
            ClusterCommand("discover", "definitely-other-user"), "sunjj", "probe", False
        )
    )[-1]
    result = subprocess.run(
        ["sh", "-c", script],
        capture_output=True,
        text=True,
        env={**os.environ, "PATH": str(tmp_path) + ":" + os.environ["PATH"]},
    )
    assert result.returncode == 92
    assert "should-not-execute" not in result.stdout


def test_current_cluster_marker_and_backup_names():
    assert parse_cluster_names(
        "  ai_perf_cluster\n  ai_perf_v2_cluster.bak\n* mdsv2-cluster\n"
    ) == ["ai_perf_cluster", "ai_perf_v2_cluster.bak", "mdsv2-cluster"]


@pytest.mark.parametrize(
    "bad", ["*", "** main", "* main extra", "*main", "* error: denied"]
)
def test_marker_does_not_relax_cluster_name_validation(bad):
    with pytest.raises(ClusterParseError):
        parse_cluster_names(bad)


@pytest.mark.parametrize("interactive", [False, True])
def test_root_switch_uses_sudo_su_login_shell(interactive):
    command = build_command(
        ClusterCommand("discover", "root"), "sunjj", "probe", interactive
    )
    assert "-u root -- su - root -c " in command
    assert " -i " not in command
    if interactive:
        assert "__DTT_AUTH_probe__%p__END__" in command
    else:
        assert "sudo -n " in command


@pytest.mark.parametrize("interactive", [False, True])
def test_nonroot_switch_sets_home_and_avoids_sudo_login_requoting(interactive):
    command = build_command(ClusterCommand("discover", "dingofs"), "sunjj", "probe", interactive)
    words = shlex.split(command)
    assert words[words.index("-u") + 1] == "dingofs"
    assert "-H" in words and "-i" not in words
    assert words[words.index("--") + 1: -1] == ["bash", "-lc"]
    assert 'p=$(command -v dingo)' in words[-1]
    assert '"$HOME" "$p"' in words[-1]
    if interactive:
        assert "__DTT_AUTH_probe__%p__END__" in words
    else:
        assert "-n" in words
