"""Read the append-only v2 functional event file without losing a cursor.

Persist ``new_offset``, ``file_identity`` and ``last_event`` together after
persisting each batch's events. Pass all three back on restart. A repeated
last sequence is accepted only when its entire JSON record is identical.
The byte cursor never advances past an incomplete line. Errors are fatal to
the stream; the caller must mark the child for attention, not reset to zero.
"""

from dataclasses import dataclass
import json
import os
from pathlib import Path
from typing import Any


class EventReadError(ValueError):
    """A cursor, file, or complete record is invalid for this child."""

    def __init__(self, code: str, detail: str):
        self.code = code
        super().__init__(f'{code}: {detail}')


@dataclass(frozen=True)
class EventBatch:
    events: list[dict[str, Any]]
    new_offset: int
    partial_tail: bool
    file_identity: dict[str, int]
    last_event: dict[str, Any] | None


_REQUIRED = ('version', 'seq', 'time', 'type', 'stage', 'parent_id',
             'child_id', 'module', 'case_path', 'attempt', 'data')


def _record(raw: bytes, byte_offset: int) -> dict[str, Any]:
    try:
        value = json.loads(raw.decode('utf-8'))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise EventReadError('malformed_record', f'byte {byte_offset}: {exc}') from exc
    if not isinstance(value, dict) or any(key not in value for key in _REQUIRED):
        raise EventReadError('malformed_record', f'byte {byte_offset}: invalid envelope')
    if value['version'] != 2 or type(value['seq']) is not int or value['seq'] <= 0:
        raise EventReadError('malformed_record', f'byte {byte_offset}: invalid version or seq')
    if (not isinstance(value['time'], str) or not isinstance(value['type'], str)
            or not isinstance(value['stage'], str)
            or any(not isinstance(value[key], str) or not value[key]
                   for key in ('parent_id', 'child_id', 'module'))
            or value['case_path'] is not None and not isinstance(value['case_path'], str)
            or value['attempt'] is not None and
            (type(value['attempt']) is not int or value['attempt'] <= 0)
            or not isinstance(value['data'], dict)):
        raise EventReadError('malformed_record', f'byte {byte_offset}: invalid envelope fields')
    return value


def _validate_anchor(stream, offset: int, last_event: dict[str, Any],
                     max_line_bytes: int) -> None:
    """Check the last committed line still exists at the committed offset."""
    start = max(0, offset - max_line_bytes - 1)
    stream.seek(start)
    tail = stream.read(offset - start)
    if not tail.endswith(b'\n'):
        raise EventReadError('cursor_mismatch', 'offset is not at a line boundary')
    prior = tail[:-1].rfind(b'\n')
    raw = tail[prior + 1:-1]
    if not raw or len(raw) + 1 > max_line_bytes:
        raise EventReadError('cursor_mismatch', 'previous line is missing or oversized')
    if _record(raw, start + prior + 1) != last_event:
        raise EventReadError('cursor_mismatch', 'last committed event changed')


def read_events(path: Path, offset: int, *,
                file_identity: dict[str, int] | None = None,
                last_event: dict[str, Any] | None = None,
                max_events: int = 1000,
                max_line_bytes: int = 1024 * 1024) -> EventBatch:
    """Read at most ``max_events`` physical lines from an append-only JSONL.

    A batch may contain fewer unique events because identical duplicates are
    consumed. ``last_event`` must be the last accepted event, including when a
    batch has no new events. The caller persists the cursor and events in one
    transaction; a partial tail is retried at the same offset after append.
    """
    if type(offset) is not int or offset < 0:
        raise EventReadError('invalid_cursor', 'offset must be a nonnegative integer')
    if type(max_events) is not int or max_events <= 0:
        raise EventReadError('invalid_limit', 'max_events must be a positive integer')
    if type(max_line_bytes) is not int or max_line_bytes < 2:
        raise EventReadError('invalid_limit', 'max_line_bytes must be at least two')
    if offset and (file_identity is None or last_event is None):
        raise EventReadError('invalid_cursor', 'nonzero offset requires identity and last event')
    if offset == 0 and (file_identity is not None or last_event is not None):
        raise EventReadError('invalid_cursor', 'initial cursor cannot carry previous state')
    try:
        with Path(path).open('rb') as stream:
            details = os.fstat(stream.fileno())
            identity = {'dev': details.st_dev, 'ino': details.st_ino}
            if file_identity is not None and file_identity != identity:
                raise EventReadError('file_identity_mismatch', 'event file was rotated')
            if offset > details.st_size:
                raise EventReadError('truncated', 'cursor extends beyond event file')
            if offset:
                _validate_anchor(stream, offset, last_event, max_line_bytes)
            stream.seek(offset)
            accepted = []
            cursor = offset
            previous = last_event
            partial = False
            for _ in range(max_events):
                raw = stream.readline(max_line_bytes + 1)
                if not raw:
                    break
                if len(raw) > max_line_bytes:
                    raise EventReadError('oversized_line', f'line at byte {cursor} exceeds limit')
                if not raw.endswith(b'\n'):
                    partial = True
                    break
                item = _record(raw[:-1], cursor)
                seq = item['seq']
                expected = previous['seq'] + 1 if previous else 1
                if previous and seq == previous['seq']:
                    if item != previous:
                        raise EventReadError('conflicting_duplicate', f'seq {seq} differs')
                elif seq != expected:
                    raise EventReadError('sequence_gap', f'expected {expected}, got {seq}')
                else:
                    accepted.append(item)
                    previous = item
                cursor = stream.tell()
            return EventBatch(accepted, cursor, partial, identity, previous)
    except OSError as exc:
        raise EventReadError('file_unavailable', str(exc)) from exc
