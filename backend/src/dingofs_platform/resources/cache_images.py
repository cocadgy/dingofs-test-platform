"""Docker Hub metadata and immutable, platform-side cache binary artifacts."""
import fcntl
import gzip
import hashlib
import json
import os
import re
import shutil
import tarfile
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

REPOSITORY = "dingodatabase/dingofs"
HUB = "https://hub.docker.com/v2/repositories/" + REPOSITORY + "/tags"
REGISTRY = "https://registry-1.docker.io/v2/" + REPOSITORY
DIGEST = re.compile(r"sha256:[0-9a-f]{64}\Z")
BINARY = "dingofs/cache/sbin/dingo-cache"
MAX_BINARY = 1024 ** 3
MAX_LAYER = 8 * 1024 ** 3
MAX_TOTAL = 16 * 1024 ** 3


class SafeRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if urllib.parse.urlsplit(newurl).scheme != "https":
            raise ValueError("镜像下载不允许跳转到非 HTTPS 地址")
        redirected = super().redirect_request(req, fp, code, msg, headers, newurl)
        if urllib.parse.urlsplit(req.full_url).netloc != urllib.parse.urlsplit(newurl).netloc:
            redirected.remove_header("Authorization")
        return redirected


def open_json(url):
    with urllib.request.urlopen(url, timeout=20) as response:
        raw = response.read(4 * 1024 * 1024 + 1)
    if len(raw) > 4 * 1024 * 1024:
        raise ValueError("版本信息超过大小限制")
    return json.loads(raw)


def list_tags(page=1, search=""):
    if not 1 <= page <= 10000 or len(search) > 128:
        raise ValueError("无效的 TAG 查询")
    query = urllib.parse.urlencode({"page": page, "page_size": 30, "ordering": "last_updated", "name": search})
    data = open_json(HUB + "?" + query)
    items = []
    for row in data["results"]:
        image = next((item for item in row.get("images", []) if item.get("os") == "linux"
                      and item.get("architecture") == "amd64" and DIGEST.fullmatch(item.get("digest", ""))), None)
        items.append({"name": row["name"], "updated_at": row.get("last_updated", ""),
                      "digest": image["digest"] if image else "", "architecture": "amd64" if image else "",
                      "available": bool(image)})
    items.sort(key=lambda item: item["updated_at"], reverse=True)
    return {"items": items, "count": data["count"], "next_page": page + 1 if data.get("next") else None}


class Registry:
    def __init__(self):
        self.opener = urllib.request.build_opener(SafeRedirect())
        self.token = ""

    def open(self, suffix):
        if not self.token:
            self.token = open_json("https://auth.docker.io/token?" + urllib.parse.urlencode({
                "service": "registry.docker.io", "scope": "repository:" + REPOSITORY + ":pull"}))["token"]
        req = urllib.request.Request(REGISTRY + suffix, headers={
            "Authorization": "Bearer " + self.token,
            "Accept": "application/vnd.oci.image.manifest.v1+json, application/vnd.docker.distribution.manifest.v2+json"})
        try:
            return self.opener.open(req, timeout=30)
        except urllib.error.HTTPError as exc:
            if exc.code == 401 and self.token:
                self.token = ""
                raise ValueError("镜像认证已过期，请重新检查") from None
            raise

    def document(self, suffix, digest):
        if not DIGEST.fullmatch(digest):
            raise ValueError("镜像摘要格式无效")
        with self.open(suffix + digest) as response:
            raw = response.read(4 * 1024 * 1024 + 1)
        if len(raw) > 4 * 1024 * 1024 or "sha256:" + hashlib.sha256(raw).hexdigest() != digest:
            raise ValueError("镜像元数据校验失败")
        return json.loads(raw)

    def manifest(self, digest):
        return self.document("/manifests/", digest)

    def config(self, digest):
        return self.document("/blobs/", digest)

    def download(self, layer, output, check):
        digest, size = layer["digest"], layer["size"]
        if not DIGEST.fullmatch(digest) or not 0 < size <= MAX_LAYER:
            raise ValueError("镜像层大小或摘要无效")
        if shutil.disk_usage(output.parent).free < size + MAX_BINARY:
            raise ValueError("平台制品缓存空间不足")
        sha, total = hashlib.sha256(), 0
        with self.open("/blobs/" + digest) as response, output.open("wb") as stream:
            while True:
                check()
                block = response.read(1024 * 1024)
                if not block:
                    break
                total += len(block)
                if total > size:
                    raise ValueError("镜像层大小与清单不一致")
                sha.update(block); stream.write(block)
        if total != size or "sha256:" + sha.hexdigest() != digest:
            raise ValueError("镜像层校验失败，未发布缓存程序")


class BoundedTarInfo(tarfile.TarInfo):
    def _proc_member(self, archive):
        if self.type in (tarfile.XHDTYPE, tarfile.XGLTYPE, tarfile.GNUTYPE_LONGNAME, tarfile.GNUTYPE_LONGLINK) and self.size > 1024 * 1024:
            raise ValueError("镜像归档扩展元数据超出限制")
        return super()._proc_member(archive)


class CheckedReader:
    def __init__(self, source, check):
        self.source, self.check, self.total = source, check, 0

    def read(self, size):
        self.check()
        data = self.source.read(min(size, 1024 * 1024))
        self.total += len(data)
        if self.total > 64 * 1024 ** 3:
            raise ValueError("镜像归档解压大小超出限制")
        return data


def extract_binary(archive, destination, check=lambda: None, binary_path=BINARY):
    """Read regular bytes only, respecting ancestor whiteouts; never extractall."""
    found, masked = False, False
    parts = binary_path.split("/")
    whiteouts = {"/".join(parts[:i] + [".wh." + parts[i]]) for i in range(len(parts))}
    whiteouts |= {"/".join(parts[:i] + [".wh..wh..opq"]) for i in range(len(parts))}
    ancestors = {"/".join(parts[:i]) for i in range(1, len(parts))}
    expanded, entries = 0, 0
    with archive.open("rb") as raw:
        magic = raw.read(2)
    opener = gzip.open if magic == bytes([31, 139]) else open
    with opener(archive, "rb") as source, tarfile.open(fileobj=CheckedReader(source, check), mode="r|", tarinfo=BoundedTarInfo) as stream:
        for member in stream:
            check()
            entries += 1; expanded += max(member.size, 0)
            if entries > 1000000 or expanded > 64 * 1024 ** 3:
                raise ValueError("镜像归档超出安全限制")
            name = member.name.removeprefix("./").rstrip("/")
            if name in whiteouts or name in ancestors and not member.isdir():
                masked = True
            if name != binary_path:
                continue
            if not member.isfile() or not 0 < member.size <= MAX_BINARY:
                raise ValueError("镜像内 dingo-cache 必须是大小有效的普通文件")
            with stream.extractfile(member) as source, destination.open("wb") as out:
                remaining = member.size
                while remaining:
                    check()
                    block = source.read(min(1024 * 1024, remaining))
                    if not block:
                        raise ValueError("镜像中的程序文件不完整")
                    out.write(block); remaining -= len(block)
            found = True
    return "found" if found else "masked" if masked else "absent"


def file_digest(path, check=lambda: None):
    result = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            check()
            result.update(block)
    return result.hexdigest()


def ensure_cached(digest, root, cancelled, deadline, component="dingo-cache"):
    if component not in ("dingo-cache", "dingo-client"):
        raise ValueError("无效的程序类型")
    binary_path = BINARY if component == "dingo-cache" else "dingofs/client/sbin/dingo-client"
    if not DIGEST.fullmatch(digest):
        raise ValueError("请选择有效的镜像 TAG")
    def check():
        if cancelled():
            raise ValueError("程序准备已取消")
        if time.monotonic() >= deadline:
            raise ValueError("程序下载或分发超时，请重试")
    check()
    root = Path(root) if component == "dingo-cache" else Path(root) / "client"
    root.mkdir(parents=True, exist_ok=True)
    key = digest.split(":")[1]
    folder = root / key
    folder.mkdir(exist_ok=True)
    with (folder / ".lock").open("a") as lock:
        while True:
            check()
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                time.sleep(0.2)
        binary, metadata = folder / component, folder / "metadata.json"
        if binary.is_file() and metadata.is_file():
            info = json.loads(metadata.read_text())
            if info.get("digest") == digest and info.get("sha256") == file_digest(binary, check):
                return {**info, "path": str(binary)}
        registry = Registry()
        manifest = registry.manifest(digest)
        config = registry.config(manifest["config"]["digest"])
        if config.get("architecture") != "amd64" or config.get("os") != "linux":
            raise ValueError("当前仅支持 Linux amd64 的 dingo-cache 镜像")
        layers = manifest.get("layers", [])
        if not layers or len(layers) > 128 or sum(item["size"] for item in layers) > MAX_TOTAL:
            raise ValueError("镜像层数量或总大小超出限制")
        with tempfile.TemporaryDirectory(prefix="prepare-", dir=folder) as staging:
            layer_path, target = Path(staging) / "layer", Path(staging) / component
            for layer in reversed(layers):
                check()
                registry.download(layer, layer_path, check)
                status = extract_binary(layer_path, target, check, binary_path=binary_path)
                layer_path.unlink()
                if status == "masked":
                    break
                if status != "found":
                    continue
                with target.open("rb") as stream:
                    header = stream.read(20)
                if header[:6] != bytes([127, 69, 76, 70, 2, 1]) or header[18:20] != bytes([62, 0]):
                    raise ValueError("镜像中的 dingo-cache 不是 Linux amd64 ELF 程序")
                info = {"digest": digest, "sha256": file_digest(target, check), "size": target.stat().st_size, "architecture": "amd64"}
                check()
                target.chmod(0o644)
                os.replace(target, binary)
                meta = Path(staging) / "metadata.json"
                meta.write_text(json.dumps(info))
                os.replace(meta, metadata)
                return {**info, "path": str(binary)}
        raise ValueError("所选 TAG 不包含 " + binary_path + "，不会使用其他版本")
