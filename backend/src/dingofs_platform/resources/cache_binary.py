"""Resolve and pin the cache executable used by a creation plan (also sent over SSH)."""
import hashlib
import json
import os
import re
import subprocess
import shutil
import tempfile
import urllib.request
from pathlib import Path

CACHE_MIRROR = "https://www.dingodb.com/dingofs"


def resolve_cache_commit(commit):
    if not re.fullmatch(r"[0-9a-fA-F]{7,40}", commit):
        raise ValueError("Commit ID 必须为 7～40 位十六进制字符")
    commit = commit.lower()
    try:
        with urllib.request.urlopen(CACHE_MIRROR + "/dingo-cache.version", timeout=20) as response:
            index = json.loads(response.read(2 * 1024 * 1024))
    except (OSError, ValueError) as exc:
        raise ValueError("无法读取 dingo-cache 版本索引：" + str(exc)) from exc
    matches = [(key, value) for key, value in index.get("commits", {}).items()
               if re.fullmatch(r"[0-9a-f]{7,40}", key)
               and key.startswith(commit)]
    if len(matches) != 1:
        raise ValueError("未找到该 commit 的已发布二进制，或 commit 前缀不唯一")
    key, detail = matches[0]
    path = detail.get("path", "")
    if path != "commits/" + key + "/dingo-cache":
        raise ValueError("制品索引中的下载路径无效")
    return {"commit": key, "url": CACHE_MIRROR + "/" + path,
            "build_time": detail.get("build_time", ""), "size": detail.get("size", "")}


def cache_file_digest(path):
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def inspect_cache_binary(path, expected_commit=""):
    path = Path(path).resolve(strict=True)
    if not path.is_file() or not os.access(path, os.X_OK):
        raise ValueError("dingo-cache 文件不存在或不可执行：" + str(path))
    result = subprocess.run([str(path), "--version"], stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, timeout=15)
    version = result.stdout.decode(errors="replace").strip()[:2048]
    if result.returncode != 0 or not version:
        raise ValueError("无法运行 dingo-cache 或读取版本：" + version)
    if expected_commit and not re.search(r"(?<![0-9a-f])" + re.escape(expected_commit) + r"[0-9a-f]*", version.lower()):
        raise ValueError("下载程序的版本与指定 commit 不一致：" + version)
    return {"path": str(path), "sha256": cache_file_digest(path), "version": version}


def prepare_cache_binary(record, component="dingo-cache"):
    if component not in ("dingo-cache", "dingo-client"):
        raise ValueError("无效的程序类型")
    source = record.get("binary_source", "default")
    commit = ""
    if source == "path":
        directory = record.get("binary_directory", "")
        if not directory.startswith("/") or ".." in Path(directory).parts:
            raise ValueError("请填写程序所在目录的绝对路径")
        path = Path(directory) / component
    elif source == "tag":
        digest = record.get("binary_digest", "")
        uploaded = record.get("binary_upload") or {}
        expected = uploaded.get("sha256", "")
        if not re.fullmatch(r"sha256:[0-9a-f]{64}", digest) or not re.fullmatch(r"[0-9a-f]{64}", expected):
            raise ValueError("TAG 程序尚未完成平台分发或校验信息无效")
        root = Path.home() / ".local/share/dingofs-platform" / ("client-binaries" if component == "dingo-client" else "cache-binaries") / digest.split(":")[1]
        root.mkdir(parents=True, exist_ok=True, mode=0o700)
        path = root / component
        if not path.is_file() or cache_file_digest(path) != expected:
            source_path = Path(uploaded.get("path", ""))
            if not source_path.is_file():
                raise ValueError("平台分发的程序文件不存在，请重新检查")
            temporary = None
            try:
                with tempfile.NamedTemporaryFile(dir=root, delete=False) as out, source_path.open("rb") as source_file:
                    temporary = Path(out.name)
                    shutil.copyfileobj(source_file, out, 1024 * 1024)
                if cache_file_digest(temporary) != expected:
                    raise ValueError("TAG 程序校验失败，不会使用其他版本")
                temporary.chmod(0o700)
                inspect_cache_binary(temporary)
                os.replace(temporary, path)
                temporary = None
            finally:
                if temporary is not None:
                    temporary.unlink(missing_ok=True)
    elif source == "commit":
        if component != "dingo-cache":
            raise ValueError("客户端请选择镜像 TAG")
        artifact = resolve_cache_commit(record.get("binary_commit", ""))
        commit = artifact["commit"]
        root = Path.home() / ".local/share/dingofs-platform/cache-binaries" / commit
        root.mkdir(parents=True, exist_ok=True, mode=0o700)
        path = root / "dingo-cache"
        if not path.exists():
            temporary = None
            try:
                with urllib.request.urlopen(artifact["url"], timeout=120) as response, tempfile.NamedTemporaryFile(dir=root, delete=False) as output:
                    temporary = Path(output.name)
                    size = 0
                    while True:
                        block = response.read(1024 * 1024)
                        if not block:
                            break
                        size += len(block)
                        if size > 512 * 1024 * 1024:
                            raise ValueError("dingo-cache 下载文件超过大小限制")
                        output.write(block)
                temporary.chmod(0o700)
                inspect_cache_binary(temporary, commit)
                os.replace(temporary, path)
            except (OSError, ValueError, subprocess.SubprocessError) as exc:
                if temporary is not None:
                    temporary.unlink(missing_ok=True)
                raise ValueError("下载或验证 dingo-cache 失败（commit " + commit + "）：" + str(exc)) from exc
    elif source == "default":
        installed = Path.home() / ".dingo/components/installed.json"
        try:
            entries = json.loads(installed.read_text())
            active = [item for item in entries if item.get("name") == component and item.get("active")]
            if len(active) != 1:
                raise ValueError("未找到唯一的默认 dingo-cache，请先安装并设置默认版本")
            path = Path(active[0]["path"]) / component
        except (OSError, KeyError, TypeError) as exc:
            raise ValueError("无法读取当前执行用户的默认 dingo-cache：" + str(exc)) from exc
    else:
        raise ValueError("无效的程序来源")
    return {**inspect_cache_binary(path, commit), "source": source, "commit": commit,
            **({"tag": record["binary_tag"], "digest": record["binary_digest"]} if source == "tag" else {})}


def verify_cache_binary(info):
    path = info.get("path", "")
    if not os.path.isabs(path) or not os.access(path, os.X_OK):
        raise ValueError("已检查的 dingo-cache 不存在或不可执行，请重新检查")
    if cache_file_digest(path) != info.get("sha256"):
        raise ValueError("dingo-cache 在检查后发生变化，请重新检查")
    return path
