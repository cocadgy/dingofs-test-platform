"""Pure, bounded reader for the frozen functional event stream."""
import json
import socket
import subprocess

import pytest


@pytest.fixture(autouse=True)
def deny_external_io(monkeypatch):
    def denied(*_args, **_kwargs):
        raise AssertionError('external I/O is forbidden in pure event tests')

    monkeypatch.setattr(socket.socket, 'connect', denied)
    monkeypatch.setattr(socket, 'create_connection', denied)
    monkeypatch.setattr(subprocess, 'Popen', denied)


def event(seq, **changes):
    record = {'version': 2, 'seq': seq, 'time': '2026-11-10T00:00:00Z',
              'type': 'attempt_started', 'stage': 'cases', 'parent_id': 'parent',
              'child_id': 'child', 'module': 'quota', 'case_path': 'a.yaml',
              'attempt': 1, 'data': {}}
    record.update(changes)
    return record


def line(record):
    return (json.dumps(record, separators=(',', ':')) + '\n').encode()


def reader():
    from dingofs_platform.functional.event_reader import read_events, EventReadError
    return read_events, EventReadError


def test_reads_12000_events_in_bounded_batches_and_restores_cursor(tmp_path):
    read_events, _ = reader()
    path = tmp_path / 'functional-events.jsonl'
    path.write_bytes(b''.join(line(event(seq)) for seq in range(1, 12001)))
    offset = 0
    previous = None
    identity = None
    received = []
    while offset < path.stat().st_size:
        batch = read_events(path, offset, file_identity=identity, last_event=previous,
                            max_events=137)
        assert len(batch.events) <= 137
        assert batch.new_offset > offset
        received.extend(item['seq'] for item in batch.events)
        offset = batch.new_offset
        identity = batch.file_identity
        previous = batch.last_event
    assert received == list(range(1, 12001))
    assert offset == path.stat().st_size


def test_partial_tail_is_not_consumed_until_newline(tmp_path):
    read_events, _ = reader()
    path = tmp_path / 'events'
    first = line(event(1))
    second = line(event(2))
    path.write_bytes(first + second[:-2])
    batch = read_events(path, 0)
    assert [item['seq'] for item in batch.events] == [1]
    assert batch.new_offset == len(first)
    assert batch.partial_tail is True
    with path.open('ab') as stream:
        stream.write(second[-2:])
    resumed = read_events(path, batch.new_offset, file_identity=batch.file_identity,
                          last_event=batch.last_event)
    assert [item['seq'] for item in resumed.events] == [2]
    assert resumed.partial_tail is False


def test_identical_duplicate_is_deduplicated_even_across_restart(tmp_path):
    read_events, _ = reader()
    path = tmp_path / 'events'
    path.write_bytes(line(event(1)) + line(event(1)) + line(event(2)))
    first = read_events(path, 0, max_events=1)
    second = read_events(path, first.new_offset, file_identity=first.file_identity,
                         last_event=first.last_event, max_events=1)
    third = read_events(path, second.new_offset, file_identity=second.file_identity,
                        last_event=second.last_event)
    assert [item['seq'] for item in first.events] == [1]
    assert second.events == []
    assert [item['seq'] for item in third.events] == [2]


@pytest.mark.parametrize('records', [
    [event(1), event(1, data={'status': 'FAIL'})],
    [event(1), event(3)],
    [event(2)],
    [event(1), event(2), event(1)],
])
def test_conflicting_duplicates_and_gaps_are_corruption(tmp_path, records):
    read_events, EventReadError = reader()
    path = tmp_path / 'events'
    path.write_bytes(b''.join(line(item) for item in records))
    with pytest.raises(EventReadError):
        read_events(path, 0)


def test_truncation_rotation_and_restart_anchor_are_refused(tmp_path):
    read_events, EventReadError = reader()
    path = tmp_path / 'events'
    path.write_bytes(line(event(1)) + line(event(2)))
    first = read_events(path, 0, max_events=1)
    path.write_bytes(b'')
    with pytest.raises(EventReadError):
        read_events(path, first.new_offset, file_identity=first.file_identity,
                    last_event=first.last_event)
    path.write_bytes(line(event(1, data={'changed': True})) + line(event(2)))
    with pytest.raises(EventReadError):
        read_events(path, first.new_offset, file_identity=first.file_identity,
                    last_event=first.last_event)
    path.rename(tmp_path / 'old-events')
    path.write_bytes(line(event(1)) + line(event(2)))
    with pytest.raises(EventReadError):
        read_events(path, first.new_offset, file_identity=first.file_identity,
                    last_event=first.last_event)


@pytest.mark.parametrize('bad', [b'\xff\n', b'{oops}\n', b'[]\n',
                                  b'{"seq":1}\n'])
def test_complete_malformed_record_is_not_skipped(tmp_path, bad):
    read_events, EventReadError = reader()
    path = tmp_path / 'events'
    path.write_bytes(line(event(1)) + bad)
    with pytest.raises(EventReadError):
        read_events(path, 0)


@pytest.mark.parametrize('offset', [-1, True, 1.2])
def test_invalid_offsets_are_refused(tmp_path, offset):
    read_events, EventReadError = reader()
    path = tmp_path / 'events'
    path.write_bytes(line(event(1)))
    with pytest.raises(EventReadError):
        read_events(path, offset)


def test_oversized_line_is_refused(tmp_path):
    read_events, EventReadError = reader()
    path = tmp_path / 'events'
    path.write_bytes(line(event(1, data={'big': 'x' * 300})))
    with pytest.raises(EventReadError):
        read_events(path, 0, max_line_bytes=128)
