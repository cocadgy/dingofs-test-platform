"""Private server-owned report sources; never resolve paths from an HTTP input.

Entries are immutable regular bytes, including materialized in-tree aliases.
The publisher is trusted; hashes are integrity evidence, not a code signature.
Mount the dedicated archive read-only in the API, independently of current I.
"""
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat

MAX_FILES = 16384
MAX_FILE_BYTES = 32 * 1024 * 1024
MAX_TOTAL_BYTES = 256 * 1024 * 1024
MAX_MANIFEST_BYTES = 4 * 1024 * 1024


def manifest_key(manifest):
    if not isinstance(manifest, dict) or not 1 <= len(manifest) <= MAX_FILES:
        raise ValueError('invalid archive manifest')
    for name, digest in manifest.items():
        if (not isinstance(name, str) or not name or len(name) > 1024
                or PurePosixPath(name).is_absolute() or PurePosixPath(name).as_posix() != name
                or '..' in PurePosixPath(name).parts or '\\' in name
                or any(ord(c) < 32 for c in name)
                or any(p == '__pycache__' for p in PurePosixPath(name).parts)
                or PurePosixPath(name).suffix in ('.pyc', '.pyo')
                or not isinstance(digest, str) or not re.fullmatch('[a-f0-9]{64}', digest)):
            raise ValueError('invalid archive manifest')
    encoded = json.dumps(manifest, sort_keys=True, separators=(',', ':')).encode()
    if len(encoded) > MAX_MANIFEST_BYTES:
        raise ValueError('archive manifest too large')
    return hashlib.sha256(encoded).hexdigest()


def _private(path, *, directory, immutable=True):
    info = path.lstat()
    if (info.st_uid not in (0, os.geteuid()) or stat.S_IMODE(info.st_mode) & (0o077 | (0o222 if immutable else 0))
            or not (stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode))):
        raise ValueError('untrusted archive permissions or type')
    return info


def _archive_root(archive):
    root = Path(archive)
    if (not root.is_absolute() or '..' in root.parts
            or any(p.is_symlink() for p in (root, *root.parents))):
        raise ValueError('unsafe archive path')
    _private(root, directory=True, immutable=False)
    return root


def resolve_archive(archive, manifest):
    root = _archive_root(archive)
    entry = root / manifest_key(manifest)
    _private(entry, directory=True)
    source = entry / 'source'
    _private(source, directory=True)
    expected_dirs = {parent.as_posix() for name in manifest for parent in PurePosixPath(name).parents
                     if parent.as_posix() != '.'}
    found, total, count = set(), 0, 0
    pending = [source]
    while pending:
        directory = pending.pop()
        for path in directory.iterdir():
            count += 1
            if count > MAX_FILES + len(expected_dirs):
                raise ValueError('archive entry limit exceeded')
            name = path.relative_to(source).as_posix()
            if name in expected_dirs:
                _private(path, directory=True)
                pending.append(path)
                continue
            info = _private(path, directory=False)
            if name not in manifest or info.st_size > MAX_FILE_BYTES:
                raise ValueError('unexpected or oversized archive file')
            total += info.st_size
            if total > MAX_TOTAL_BYTES:
                raise ValueError('archive size limit exceeded')
            with path.open('rb') as stream:
                data = stream.read(MAX_FILE_BYTES + 1)
            if len(data) != info.st_size or hashlib.sha256(data).hexdigest() != manifest[name]:
                raise ValueError('archive source changed')
            found.add(name)
    if found != manifest.keys():
        raise ValueError('archive source missing')
    return source


def main():
    """Deployment utility: calculate the exact key or verify an already staged entry."""
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('key', 'verify'))
    parser.add_argument('--manifest', required=True, type=Path)
    parser.add_argument('--archive', type=Path)
    args = parser.parse_args()
    with args.manifest.open('rb') as stream:
        data = stream.read(MAX_MANIFEST_BYTES + 1)
    if len(data) > MAX_MANIFEST_BYTES:
        raise ValueError('archive manifest too large')
    manifest = json.loads(data)
    key = manifest_key(manifest)
    if args.action == 'verify':
        if args.archive is None: parser.error('--archive is required for verify')
        resolve_archive(args.archive, manifest)
    print(key)


if __name__ == '__main__':
    main()
