"""Read predefined integration environments without persisting their secrets."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path

from ruamel.yaml import YAML

from ..contracts import EnvironmentDescriptor
from ..source_bridge import inspect_source

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
    client_count: int | None
    cache_count: int | None
    template: bool
    runnable: bool
    issue: str | None
    descriptor: EnvironmentDescriptor


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
    """Legacy copy-settings/lease compatibility only; never used by guided scan.

    Task9b must replace this duplicated resolver with a framework-owned portable
    settings projection retaining inherited flags and unexpanded cache counts.
    EnvironmentDescriptor intentionally cannot reconstruct those settings.
    """
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
    """Enumerate metadata locally; resolve only through the trusted framework.

    ``root`` must be the server-configured checkout's conf/env directory.
    ``runnable`` retains the legacy source-completeness meaning; compatibility
    with selected cases and remote execution still require guided preflight.
    """
    root = Path(root)
    if root.name != 'env' or root.parent.name != 'conf' or '..' in root.parts:
        raise ValueError('invalid environment source directory')
    trusted = root.parent.parent.resolve()
    if not root.resolve().is_relative_to(trusted):
        raise ValueError('invalid environment source directory')
    root = trusted / 'conf/env'
    sources: dict[str, tuple[Path, str | None]] = {}
    for path in sorted(root.glob('*.yaml')):
        try:
            if not path.resolve().is_relative_to(trusted) or not path.is_file() or path.stat().st_size > 1024 * 1024:
                raise ValueError
            document = _yaml.load(path.read_text()) or {}
            if not isinstance(document, dict):
                raise ValueError
            for key, raw in document.items():
                if not isinstance(key, str) or not isinstance(raw, dict):
                    raise ValueError
                base = raw.get('base')
                if base is not None and not isinstance(base, str):
                    raise ValueError
                if key in sources:
                    raise ValueError('duplicate environment name')
                sources[key] = (path, base)
        except Exception as exc:
            if isinstance(exc, ValueError) and str(exc) == 'duplicate environment name':
                raise ValueError('duplicate environment name') from None
            raise ValueError('invalid environment source') from None
    referenced = {base for _, base in sources.values() if base}
    descriptors: list[PresetDescriptor] = []
    for key in sorted(sources):
        path, base = sources[key]
        value = inspect_source(trusted, key, {})
        hosts = tuple(sorted({target.host for target in value.targets if target.role == 'client'}))
        template = key in referenced
        issues = list(value.issues)
        if template:
            issues.append('environment is an inheritance template')
        if not value.mds_addresses:
            issues.append('MDS addresses are missing')
        if not hosts or not value.client_count:
            issues.append('client configuration is missing or unknown')
        if not value.storage_type:
            issues.append('storage configuration is missing')
        descriptors.append(PresetDescriptor(
            key=key, source_file=path.name, base=base, source_digest=value.digest,
            source_file_sha=value.source_manifest.get(path.relative_to(trusted).as_posix(), ''),
            storage_file_sha=value.source_manifest.get('conf/storage.yaml', ''),
            mds_addresses=tuple(value.mds_addresses), client_hosts=hosts,
            storage_type=value.storage_type or '', client_count=value.client_count,
            cache_count=value.cache_count, template=template, runnable=not issues,
            issue='; '.join(issues) or None, descriptor=value,
        ))
    return descriptors
