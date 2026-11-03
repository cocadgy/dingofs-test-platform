import hashlib
import time
from pathlib import Path
from types import SimpleNamespace
import pytest
from dingofs_platform.resources import cache_binary

DIGEST = "sha256:" + "a" * 64


def test_tag_program_is_installed_in_target_home_and_existing_default_is_untouched(tmp_path, monkeypatch):
    source = tmp_path / "upload"
    source.write_bytes(b"image-program")
    monkeypatch.setattr(cache_binary.Path, "home", lambda: tmp_path / "home")
    monkeypatch.setattr(cache_binary.subprocess, "run", lambda *a, **k: SimpleNamespace(returncode=0, stdout=b"main-fe4384a [ci/cd]"))
    info = cache_binary.prepare_cache_binary({
        "binary_source": "tag", "binary_tag": "fe4384a", "binary_digest": DIGEST,
        "binary_upload": {"path": str(source), "sha256": hashlib.sha256(b"image-program").hexdigest()},
    })
    assert info["tag"] == "fe4384a"
    assert info["digest"] == DIGEST
    assert Path(info["path"]).read_bytes() == b"image-program"
    assert str(tmp_path / "home") in info["path"]
    assert not (tmp_path / "home/.dingo").exists()


def test_bad_uploaded_checksum_never_publishes_a_program(tmp_path, monkeypatch):
    source = tmp_path / "upload"
    source.write_bytes(b"bad")
    monkeypatch.setattr(cache_binary.Path, "home", lambda: tmp_path / "home")
    with pytest.raises(ValueError, match="校验"):
        cache_binary.prepare_cache_binary({"binary_source": "tag", "binary_tag": "latest", "binary_digest": DIGEST,
                                          "binary_upload": {"path": str(source), "sha256": "f" * 64}})
    assert not list((tmp_path / "home").rglob("dingo-cache"))
