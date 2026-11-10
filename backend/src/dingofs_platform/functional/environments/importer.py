"""Read predefined integration environments without persisting their secrets."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from hashlib import sha256
import json
from pathlib import Path

from ruamel.yaml import YAML

_yaml = YAML(typ="safe")


@dataclass(frozen=True)
class PresetDescriptor:
    key: str
    source_file: str
    base: str | None
    source_digest: str
    source_file_sha: str
    storage_file_sha: str
    mds_addresses: tuple[str, ...]
    client_hosts: tuple[str, ...]
    storage_type: str
    client_count: int
    cache_count: int
    template: bool
    runnable: bool
    issue: str | None


def _merge(base: dict, override: dict, *, root: bool = True) -> dict:
    result = deepcopy(base)
    if root:
        for name in ("client_count", "remote_cache_count"):
            result.pop(name, None)
    for name, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(name), dict):
            result[name] = _merge(result[name], value, root=False)
        elif isinstance(value, list) and isinstance(result.get(name), list):
            parent = result[name]
            result[name] = [
                _merge(parent[index], item, root=False)
                if index < len(parent) and isinstance(parent[index], dict) and isinstance(item, dict)
                else deepcopy(item)
                for index, item in enumerate(value)
            ]
        else:
            result[name] = deepcopy(value)
    return result


def read_predefined(root: Path):
    root = Path(root)
    sources: dict[str, tuple[Path, dict]] = {}
    for path in sorted(root.glob("*.yaml")):
        if path.is_symlink() or not path.is_file():
            continue
        try:
            document = _yaml.load(path.read_text()) or {}
        except Exception as exc:
            raise ValueError(f"invalid YAML in {path.name}: {exc}") from exc
        if not isinstance(document, dict):
            raise ValueError(f"invalid environment document: {path.name}")
        for key, raw in document.items():
            if not isinstance(key, str) or not isinstance(raw, dict):
                raise ValueError(f"invalid environment entry in {path.name}: {key}")
            if key in sources:
                raise ValueError(f"Duplicate environment name: {key}")
            sources[key] = (path, raw)

    resolved: dict[str, dict] = {}
    issues: dict[str, str] = {}

    def resolve(key: str, ancestors: tuple[str, ...] = ()) -> dict:
        if key in ancestors:
            raise ValueError("environment inheritance cycle: " + " -> ".join((*ancestors, key)))
        if key in resolved:
            return resolved[key]
        if key not in sources:
            raise ValueError(f"missing environment base: {key}")
        raw = sources[key][1]
        base = raw.get("base")
        if base is not None and not isinstance(base, str):
            raise ValueError(f"invalid base for {key}")
        if base:
            parent=resolve(base, (*ancestors, key))
            if base in issues:issues[key]='base environment is not runnable'
            for collection in ('clients','remote_caches'):
                if collection in raw and len(parent.get(collection,[]))!=len(raw[collection]) and raw.get('replace_'+collection) is not True:
                    issues[key]=f'array length mismatch: {collection}'
            value=_merge(parent,raw)
            if 'hosts' in raw:
                for collection in ('clients','remote_caches'):
                    if collection not in raw:value[collection]=[]
        else:value=deepcopy(raw)
        for collection in ("clients", "remote_caches"):
            if raw.get("replace_" + collection) is True:
                value[collection] = deepcopy(raw.get(collection, []))
        resolved[key] = value
        return value

    for key in sources:
        resolve(key)
    return sources, resolved, issues


def scan_predefined(root: Path) -> list[PresetDescriptor]:
    root = Path(root)
    sources, resolved, issues = read_predefined(root)
    referenced = {raw.get("base") for _, raw in sources.values() if raw.get("base")}
    storage_file = root.parent / "storage.yaml"
    storage_digest = sha256(storage_file.read_bytes()).hexdigest() if storage_file.is_file() else ""
    descriptors: list[PresetDescriptor] = []
    for key in sorted(sources):
        path, raw = sources[key]
        value = resolved[key]
        clients = value.get("clients") or value.get("hosts") or []
        if not isinstance(clients, list):
            raise ValueError(f"invalid clients for {key}")
        mds = str(value.get("mds_addr") or "")
        addresses = tuple(item.strip() for item in mds.split(",") if item.strip())
        hosts = tuple(sorted({str(item.get("host")) for item in clients if isinstance(item, dict) and item.get("host")}))
        storage = value.get("storage") or {}
        storage_type = str(storage.get("storage_type") or "") if isinstance(storage, dict) else ""
        effective_json = json.dumps(value, sort_keys=True, ensure_ascii=False, default=str)
        digest = sha256((effective_json + storage_digest).encode()).hexdigest()
        count = sum(max(1, int(item.get("client_count") or 1)) for item in clients if isinstance(item, dict))
        cache_count = sum(max(1, int(item.get("remote_cache_count") or 1)) for item in value.get("remote_caches", []) if isinstance(item, dict))
        template = key in referenced
        descriptors.append(PresetDescriptor(key, path.name, raw.get("base"), digest,
                                             sha256(path.read_bytes()).hexdigest(), storage_digest,
                                             addresses, hosts, storage_type, count, cache_count,
                                             template, bool(addresses and clients and storage_type and not template and key not in issues),
                                             issues.get(key)))
    return descriptors
