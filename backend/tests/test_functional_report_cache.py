"""Snapshot integrity, bounded storage, and coordination across API workers."""
import base64
import io
import hashlib
import json
import multiprocessing
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import time

import pytest

from dingofs_platform.errors import Problem
from test_functional_report_api import bundle


def cache_api():
    from dingofs_platform.functional.report_cache import cached_report
    return cached_report


def test_disk_snapshot_survives_new_reader_and_remote_failure(tmp_path):
    calls = []
    def fetch():
        calls.append(1)
        return bundle({'index.html': b'hello secret', 'data/a.json': b'{}', 'image.png': b'\x00\xff'})
    root = tmp_path / 'cache'
    assert cache_api()(root, 100000, 'a' * 64, 'index.html', fetch) == b'hello secret'
    def offline():
        raise RuntimeError('SSH offline')
    assert cache_api()(root, 100000, 'a' * 64, 'data/a.json', offline) == b'{}'
    assert cache_api()(root, 100000, 'a' * 64, 'image.png', offline) == b'\x00\xff'
    assert len(calls) == 1
    assert root.stat().st_mode & 0o077 == 0
    assert all(path.stat().st_mode & 0o077 == 0 for path in root.rglob('*'))


@pytest.mark.parametrize('name,kind', [('../escape', 'file'), ('/escape', 'file'),
    ('a/../../escape', 'file'), ('a\\b', 'file'), ('index.html', 'symlink'),
    ('index.html', 'hardlink'), ('index.html', 'fifo'), ('./index.html', 'file')])
def test_unsafe_bundle_never_publishes_and_retry_works(tmp_path, name, kind):
    stream = io.BytesIO()
    with tarfile.open(fileobj=stream, mode='w') as archive:
        item = tarfile.TarInfo(name)
        if kind != 'file':
            item.type = {'symlink': tarfile.SYMTYPE, 'hardlink': tarfile.LNKTYPE, 'fifo': tarfile.FIFOTYPE}[kind]
            item.linkname = '/etc/passwd'
        archive.addfile(item)
    with pytest.raises(Problem):
        cache_api()(tmp_path / 'cache', 100000, 'a' * 64, 'index.html',
                    lambda: {'bundle': base64.b64encode(stream.getvalue()).decode()})
    assert not (tmp_path / 'cache' / ('a' * 64)).exists()
    assert cache_api()(tmp_path / 'cache', 100000, 'a' * 64, 'index.html',
                       lambda: bundle({'index.html': b'retry'})) == b'retry'


def test_limits_and_eviction(tmp_path, monkeypatch):
    from dingofs_platform.functional import report_cache as module
    monkeypatch.setattr(module, 'MAX_REPORT_BYTES', 20)
    monkeypatch.setattr(module, 'MAX_TREE_BYTES', 30)
    monkeypatch.setattr(module, 'MAX_TREE_FILES', 3)
    for files in ({'index.html': b'x' * 21}, {'index.html': b'x' * 20, 'a': b'x' * 20},
                  {'index.html': b'', 'a': b'', 'b': b'', 'c': b''}):
        with pytest.raises(Problem):
            cache_api()(tmp_path / 'cache', 100000, 'a' * 64, 'index.html', lambda: bundle(files))
    root = tmp_path / 'cache'
    cache_api()(root, 100000, 'a' * 64, 'index.html', lambda: bundle({'index.html': b'first'}))
    cache_api()(root, 100000, 'b' * 64, 'index.html', lambda: bundle({'index.html': b'second'}))
    # Capacity includes allocated file blocks and entry metadata, not just payload bytes.
    cache_api()(root, 16384, 'c' * 64, 'index.html', lambda: bundle({'index.html': b'third'}))
    assert not (root / ('a' * 64)).exists()
    with pytest.raises(Problem) as error:
        cache_api()(root, 1, 'd' * 64, 'index.html', lambda: bundle({'index.html': b'x'}))
    assert error.value.code == 'report_cache_capacity'


def _parallel_reader(root, queue, start):
    start.wait()
    def fetch():
        queue.put('fetch')
        time.sleep(.1)
        return bundle({'index.html': b'snapshot'})
    queue.put(cache_api()(Path(root), 100000, 'a' * 64, 'index.html', fetch))


def test_workers_share_one_atomic_fill(tmp_path):
    context = multiprocessing.get_context('fork')
    queue, start = context.Queue(), context.Event()
    workers = [context.Process(target=_parallel_reader, args=(str(tmp_path / 'cache'), queue, start)) for _ in range(4)]
    for worker in workers: worker.start()
    start.set()
    for worker in workers:
        worker.join(10)
        assert worker.exitcode == 0
    events = [queue.get(timeout=2) for _ in range(5)]
    assert events.count('fetch') == 1
    assert events.count(b'snapshot') == 4


def test_remote_bundle_reads_tree_once_and_rejects_symlink(tmp_path):
    from dingofs_platform.functional.report_cache import report_bundle_code
    report = tmp_path / 'output' / 'report'
    report.mkdir(parents=True)
    (report / 'index.html').write_bytes(b'unchanged')
    (report / 'data').mkdir()
    (report / 'data' / 'summary.json').write_bytes(b'{}')
    code = report_bundle_code(str(report.parent), 'report/index.html')
    def remote():
        return json.loads(subprocess.check_output([sys.executable, '-I', '-c', code]))
    assert cache_api()(tmp_path / 'cache', 100000, 'a' * 64, 'data/summary.json', remote) == b'{}'
    (report / 'link').symlink_to('/etc/passwd')
    assert remote().get('error') == 'unsafe_report'


def test_malformed_or_incomplete_bundle_and_unsafe_requests(tmp_path):
    complete = base64.b64decode(bundle({'index.html': b'x'})['bundle'])
    for raw in ({'bundle': '%%%invalid'}, {'bundle': base64.b64encode(b'bad tar').decode()},
                {'bundle': base64.b64encode(complete[:1024]).decode()},
                bundle({'other.html': b'no index'}), {'missing': True}):
        with pytest.raises(Problem):
            cache_api()(tmp_path / 'cache', 100000, 'a' * 64, 'index.html', lambda: raw)
    for name in ('../escape', '/etc/passwd', 'a/../index.html', 'a\\b'):
        with pytest.raises(Problem):
            cache_api()(tmp_path / 'cache', 100000, 'a' * 64, name,
                        lambda: bundle({'index.html': b'valid'}))


def test_cache_metadata_stays_bounded_when_reports_are_evicted(tmp_path):
    root = tmp_path / 'cache'
    for number in range(270):
        key = hashlib.sha256(str(number).encode()).hexdigest()
        cache_api()(root, 16384, key, 'index.html', lambda: bundle({'index.html': b'x'}))
    assert len(list((root / 'locks').iterdir())) <= 256


def test_publication_failure_has_no_ready_snapshot_and_can_retry(tmp_path, monkeypatch):
    from dingofs_platform.functional import report_cache as module
    rename = module.os.rename
    def fail(*args):
        raise OSError('disk failure')
    monkeypatch.setattr(module.os, 'rename', fail)
    root = tmp_path / 'cache'
    with pytest.raises(Problem):
        cache_api()(root, 100000, 'a' * 64, 'index.html', lambda: bundle({'index.html': b'x'}))
    assert not (root / ('a' * 64)).exists()
    assert not list(root.glob('.staging-*'))
    monkeypatch.setattr(module.os, 'rename', rename)
    assert cache_api()(root, 100000, 'a' * 64, 'index.html', lambda: bundle({'index.html': b'retry'})) == b'retry'
