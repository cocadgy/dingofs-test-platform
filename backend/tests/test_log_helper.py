import os

import pytest
from dingofs_platform.remote import log_helper


def test_lists_regular_files_and_internal_symlinks_only(tmp_path):
    root = tmp_path / "logs"
    root.mkdir()
    (root / "app.log").write_text("one\ntwo\n")
    (root / "latest").symlink_to("app.log")
    (root / "absolute").symlink_to(root / "app.log")
    (root / "escape").symlink_to(tmp_path / "secret")
    (tmp_path / "secret").write_text("secret")
    os.mkfifo(root / "fifo")
    (root / "dir").mkdir()
    with log_helper.LogRoot(str(root)) as logs:
        result = logs.list_files()
        assert {f["name"] for f in result["files"]} == {"app.log", "latest", "absolute"}
        assert result["truncated"] is False
        assert logs.read("latest", lines=1)["text"] == "two\n"


@pytest.mark.parametrize(
    "name", ["../secret", "/etc/passwd", ".", "..", "dir/file", "x\x00y"]
)
def test_leaf_names_cannot_escape_root(tmp_path, name):
    with (
        log_helper.LogRoot(str(tmp_path)) as logs,
        pytest.raises(log_helper.LogError, match="invalid_file"),
    ):
        logs.read(name)


def test_refuses_symlink_escape_and_special_files(tmp_path):
    root = tmp_path / "logs"
    root.mkdir()
    (tmp_path / "secret").write_text("secret")
    (root / "outside").symlink_to("../secret")
    (root / "magic").symlink_to("/proc/self/environ")
    os.mkfifo(root / "fifo")
    with log_helper.LogRoot(str(root)) as logs:
        for name in ("outside", "magic", "fifo"):
            with pytest.raises(log_helper.LogError):
                logs.read(name)


def test_pinned_root_and_internal_nested_symlink(tmp_path):
    root = tmp_path / "logs"
    root.mkdir()
    (root / "dir").mkdir()
    (root / "dir" / "file").write_text("safe")
    (root / "latest").symlink_to("dir/../dir/file")
    with log_helper.LogRoot(str(root)) as logs:
        root.rename(tmp_path / "old")
        root.mkdir()
        (root / "latest").write_text("unsafe")
        assert logs.read("latest")["text"] == "safe"


def test_tail_limits_strips_ansi_and_handles_invalid_utf8(tmp_path):
    (tmp_path / "app").write_bytes(
        b"old\n" + b"a" * (2 * 1048576) + b"\n\x1b[31mred\x1b[0m\xff\n"
    )
    with log_helper.LogRoot(str(tmp_path)) as logs:
        value = logs.read("app", lines=1000)
        assert len(value["text"].encode("utf8")) <= 1048580
        assert value["text"].endswith("red\ufffd\n")
        assert "\x1b" not in value["text"]
        assert value["truncated"]


def test_cursor_resume_rotation_and_truncation(tmp_path):
    path = tmp_path / "app"
    path.write_text("first\n")
    with log_helper.LogRoot(str(tmp_path)) as logs:
        first = logs.read("app")
        with path.open("a") as stream:
            stream.write("second\n")
        second = logs.read("app", cursor=first["cursor"])
        assert second["text"] == "second\n"
        assert not second["reset"]
        path.rename(tmp_path / "old")
        path.write_text("new\n")
        rotated = logs.read("app", cursor=second["cursor"])
        assert rotated["text"] == "new\n"
        assert rotated["reset"]
        path.write_text("x")
        assert logs.read("app", cursor=rotated["cursor"])["reset"]


def test_download_is_fixed_at_initial_size_and_rejects_excess(tmp_path):
    path = tmp_path / "app"
    path.write_bytes(b"first")
    with log_helper.LogRoot(str(tmp_path)) as logs:
        download = logs.download("app", max_bytes=5)
        assert next(download) == {"type": "download_start", "name": "app", "size": 5}
        with path.open("ab") as stream:
            stream.write(b"new")
        assert b"".join(v["data"] for v in download) == b"first"
        with pytest.raises(log_helper.LogError, match="download_too_large"):
            list(logs.download("app", max_bytes=5))


def test_listing_has_bounded_scan(tmp_path):
    for i in range(1002):
        (tmp_path / str(i)).touch()
    with log_helper.LogRoot(str(tmp_path)) as logs:
        result = logs.list_files()
        assert len(result["files"]) == 1000
        assert result["truncated"]


def test_follow_decodes_utf8_and_strips_control_across_chunks(tmp_path):
    path = tmp_path / "app"
    path.write_bytes(b"start\n")
    with log_helper.LogRoot(str(tmp_path)) as logs:
        stream = logs.follow("app", interval=0)
        assert next(stream)["text"] == "start\n"
        with path.open("ab") as f:
            f.write(b"\xe4\xb8")
        partial = next(stream)
        assert partial["text"] == ""
        with path.open("ab") as f:
            f.write(b"\xad\x1b[31")
        assert next(stream)["text"] == "\u4e2d"
        with path.open("ab") as f:
            f.write(b"mred\x1b[0m")
        assert next(stream)["text"] == "red"
        stream.close()


def test_decoded_text_never_exceeds_response_byte_limit(tmp_path):
    (tmp_path / "app").write_bytes(b"\xff" * 1048576)
    with log_helper.LogRoot(str(tmp_path)) as logs:
        event = logs.read("app")
        assert len(event["text"].encode("utf8")) <= 1048576
        assert event["truncated"]


def test_symlink_loop_fails_closed(tmp_path):
    (tmp_path / "one").symlink_to("two")
    (tmp_path / "two").symlink_to("one")
    with (
        log_helper.LogRoot(str(tmp_path)) as logs,
        pytest.raises(log_helper.LogError, match="path_escape"),
    ):
        logs.read("one")


def test_symlink_replacement_during_resolution_keeps_pinned_target(
    tmp_path, monkeypatch
):
    root = tmp_path / "logs"
    root.mkdir()
    (root / "safe").write_text("safe")
    (tmp_path / "secret").write_text("secret")
    latest = root / "latest"
    latest.symlink_to("safe")
    real_readlink = os.readlink
    swapped = False

    def swap_before_readlink(path, **kwargs):
        nonlocal swapped
        if path == "" and not swapped:
            replacement = root / "replacement"
            replacement.symlink_to("../secret")
            replacement.replace(latest)
            swapped = True
        return real_readlink(path, **kwargs)

    with log_helper.LogRoot(str(root)) as logs:
        monkeypatch.setattr(os, "readlink", swap_before_readlink)
        assert logs.read("latest")["text"] == "safe"
        with pytest.raises(log_helper.LogError, match="path_escape"):
            logs.read("latest")


def test_download_truncation_is_reported(tmp_path):
    path = tmp_path / "app"
    path.write_bytes(b"abcdef")
    with log_helper.LogRoot(str(tmp_path)) as logs:
        stream = logs.download("app")
        next(stream)
        path.write_bytes(b"")
        with pytest.raises(log_helper.LogError, match="file_truncated"):
            next(stream)


def test_search_directory_bounded_and_context(tmp_path):
    from dingofs_platform.remote.log_helper import LogRoot
    (tmp_path / 'server.log').write_text('before\nERROR here\nafter\n')
    (tmp_path / 'archive.gz').write_text('ERROR hidden')
    (tmp_path / 'binary.log').write_bytes(b'foo\x00ERROR')
    (tmp_path / 'sub').mkdir()
    (tmp_path / 'sub' / 'nested.log').write_text('ERROR hidden')
    with LogRoot(str(tmp_path)) as root:
        result = root.search('error', case_sensitive=False)
    assert [(hit['name'], hit['line']) for hit in result['hits']] == [('server.log', 2)]
    assert result['hits'][0]['before'] == ['before']
    assert result['hits'][0]['after'] == ['after']
    assert result['scanned_files'] == 1
    assert result["skipped_files"] >= 1


def test_search_rejects_invalid_keyword(tmp_path):
    import pytest
    from dingofs_platform.remote.log_helper import LogRoot, LogError
    with LogRoot(str(tmp_path)) as root:
        with pytest.raises(LogError):
            root.search('')


def test_search_full_file_finds_match_after_default_prefix(tmp_path):
    from dingofs_platform.remote.log_helper import LogRoot
    (tmp_path / 'late.log').write_bytes(b'ordinary line\n' * 90000 + b'TARGET near end\n')
    with LogRoot(str(tmp_path)) as root:
        prefix = root.search('TARGET')
        full = root.search('TARGET', scan_mode='full', max_total_mb=4)
    assert prefix['hits'] == []
    assert prefix['truncated'] is True
    assert [(hit['name'], hit['text']) for hit in full['hits']] == [('late.log', 'TARGET near end')]
    assert full['truncated'] is False


def test_search_configurable_limits_are_enforced(tmp_path):
    import pytest
    from dingofs_platform.remote.log_helper import LogRoot, LogError
    (tmp_path / 'events.log').write_text('x\n' * 100 + 'TARGET\n')
    with LogRoot(str(tmp_path)) as root:
        result = root.search('x', max_hits=3)
        assert len(result['hits']) == 3
        assert result['reason'] == 'match_limit'
        with pytest.raises(LogError):
            root.search('x', max_files=1001)


def test_search_unlimited_total_bytes_and_results(tmp_path):
    from dingofs_platform.remote.log_helper import LogRoot
    (tmp_path / 'events.log').write_bytes((b'MATCH ' + b'x' * 1100 + b'\n') * 3000)
    with LogRoot(str(tmp_path)) as root:
        result = root.search('MATCH', scan_mode='full', max_total_mb=0, max_hits=0)
    assert result['scanned_bytes'] > 1048576
    assert len(result['hits']) > 500
    assert result['reason'] == 'result_bytes_limit'


def test_search_excerpt_contains_match_late_on_last_line(tmp_path):
    from dingofs_platform.remote.log_helper import LogRoot
    (tmp_path / 'long.log').write_text('a' * 4000 + 'TARGET')
    with LogRoot(str(tmp_path)) as root:
        result = root.search('TARGET')
    assert 'TARGET' in result['hits'][0]['text']


def test_search_progress_advances_once_per_completed_file(tmp_path):
    from dingofs_platform.remote.log_helper import LogRoot
    (tmp_path / 'a.log').write_text('MATCH\n')
    (tmp_path / 'b.log').write_text('MATCH\n')
    events = []
    with LogRoot(str(tmp_path)) as root:
        result = root.search('MATCH', progress=events.append)
    counts = [(event['completed_files'], event['total_files']) for event in events]
    assert counts[0] == (0, 2)
    assert counts[-1] == (2, 2)
    assert (1, 2) in counts
    assert result['scanned_files'] == 2
    assert (result['completed_files'], result['total_files']) == (2, 2)
