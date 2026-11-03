import hashlib
import io
import json
import tarfile
import time
from pathlib import Path
import pytest

DIGEST = "sha256:" + "a" * 64


def test_tag_list_requests_latest_first_and_preserves_manifest_digest(monkeypatch):
    from dingofs_platform.resources import cache_images as images
    seen = []
    def query(url):
        seen.append(url)
        return {"count": 2, "next": "page2", "results": [
            {"name": "old", "last_updated": "2026-10-01T00:00:00Z", "images": [{"os": "linux", "architecture": "amd64", "digest": DIGEST}]},
            {"name": "new", "last_updated": "2026-11-01T00:00:00Z", "images": [{"os": "linux", "architecture": "amd64", "digest": DIGEST}]},
        ]}
    monkeypatch.setattr(images, "open_json", query)
    result = images.list_tags(1, "v5.2")
    assert "ordering=last_updated" in seen[0]
    assert "name=v5.2" in seen[0]
    assert [item["name"] for item in result["items"]] == ["new", "old"]
    assert result["items"][0]["digest"] == DIGEST
    assert result["next_page"] == 2


def archive(path, entries):
    with tarfile.open(path, "w:gz") as out:
        for name, content, kind in entries:
            info = tarfile.TarInfo(name)
            if kind == "link":
                info.type = tarfile.SYMTYPE
                info.linkname = "/etc/passwd"
                out.addfile(info)
            else:
                info.size = len(content)
                out.addfile(info, io.BytesIO(content))


def test_extraction_only_writes_selected_regular_file(tmp_path):
    from dingofs_platform.resources import cache_images as images
    layer = tmp_path / "layer.gz"
    archive(layer, [("../../outside", b"bad", "file"), ("dingofs/cache/sbin/dingo-cache", b"binary", "file")])
    output = tmp_path / "binary"
    assert images.extract_binary(layer, output) == "found"
    assert output.read_bytes() == b"binary"
    assert sorted(p.name for p in tmp_path.iterdir()) == ["binary", "layer.gz"]


def test_whiteout_stops_search_and_symlink_is_not_executable(tmp_path):
    from dingofs_platform.resources import cache_images as images
    layer = tmp_path / "layer.gz"
    archive(layer, [("dingofs/cache/.wh.sbin", b"", "file")])
    assert images.extract_binary(layer, tmp_path / "binary") == "masked"
    archive(layer, [("dingofs/cache/sbin/dingo-cache", b"", "link")])
    with pytest.raises(ValueError, match="普通文件"):
        images.extract_binary(layer, tmp_path / "binary")


def test_cache_reuses_verified_binary_and_rejects_cancelled_work(tmp_path, monkeypatch):
    from dingofs_platform.resources import cache_images as images
    body = bytes([127, 69, 76, 70]) + bytes([2, 1]) + bytes(12) + bytes([62, 0]) + bytes(32)
    archive_path = tmp_path / "input.gz"
    archive(archive_path, [("dingofs/cache/sbin/dingo-cache", body, "file")])
    blob = archive_path.read_bytes()
    blob_digest = "sha256:" + hashlib.sha256(blob).hexdigest()
    calls = []
    class Registry:
        def manifest(self, digest):
            assert digest == DIGEST
            return {"layers": [{"digest": blob_digest, "size": len(blob)}], "config": {"digest": "config"}}
        def config(self, digest):
            return {"architecture": "amd64", "os": "linux"}
        def download(self, layer, output, check):
            calls.append(layer["digest"]); check(); output.write_bytes(blob)
    monkeypatch.setattr(images, "Registry", Registry)
    root = tmp_path / "cache"
    first = images.ensure_cached(DIGEST, root, lambda: False, time.monotonic() + 10)
    second = images.ensure_cached(DIGEST, root, lambda: False, time.monotonic() + 10)
    assert first["sha256"] == hashlib.sha256(body).hexdigest()
    assert Path(second["path"]).read_bytes() == body
    assert calls == [blob_digest]
    with pytest.raises(ValueError, match="取消"):
        images.ensure_cached(DIGEST, root, lambda: True, time.monotonic() + 10)


def test_tag_requires_immutable_digest_and_rejects_arbitrary_url():
    from dingofs_platform.resources.schemas import validate
    member = {"machine_id": "m", "target_user": "u", "listen_ip": "127.0.0.1", "cache_dir": "/tmp/cache",
              "binary_source": "tag", "binary_tag": "v5.2-latest", "binary_digest": DIGEST}
    normalized = validate("cache.plan", {"group_name": "g", "members": [member]})
    assert normalized["members"][0]["binary_digest"] == DIGEST
    with pytest.raises(ValueError):
        validate("cache.plan", {"group_name": "g", "members": [{**member, "binary_digest": "https://example.com/bin"}]})


def test_download_rejects_corrupt_layer_bytes_before_extraction(tmp_path, monkeypatch):
    from dingofs_platform.resources import cache_images as images
    registry = images.Registry()
    monkeypatch.setattr(registry, "open", lambda suffix: io.BytesIO(b"corrupt"))
    monkeypatch.setattr(images.shutil, "disk_usage", lambda path: type("Space", (), {"free": 10 * 1024 ** 3})())
    with pytest.raises(ValueError, match="校验失败"):
        registry.download({"digest": "sha256:" + hashlib.sha256(b"correct").hexdigest(), "size": 7}, tmp_path / "blob", lambda: None)


def test_oversized_pax_metadata_is_rejected_before_parser_allocation(tmp_path):
    from dingofs_platform.resources import cache_images as images
    layer = tmp_path / "pax.gz"
    with tarfile.open(layer, "w:gz") as out:
        header = tarfile.TarInfo("pax")
        header.type = tarfile.XGLTYPE
        header.size = 2 * 1024 * 1024
        out.addfile(header, io.BytesIO(bytes(header.size)))
    with pytest.raises(ValueError, match="元数据"):
        images.extract_binary(layer, tmp_path / "binary")


def test_skipped_payload_still_checks_cancellation(tmp_path):
    from dingofs_platform.resources import cache_images as images
    layer = tmp_path / "skip.gz"
    archive(layer, [("unrelated", bytes(2 * 1024 * 1024), "file"), ("dingofs/cache/sbin/dingo-cache", b"bin", "file")])
    checks = []
    def check():
        checks.append(True)
        if len(checks) >= 10:
            raise ValueError("取消")
    with pytest.raises(ValueError, match="取消"):
        images.extract_binary(layer, tmp_path / "binary", check)
    assert not (tmp_path / "binary").exists()
