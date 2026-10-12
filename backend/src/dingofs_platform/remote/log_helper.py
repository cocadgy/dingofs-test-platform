"""Standalone, read-only remote log program; all file resolution is descriptor based.

This module is sent verbatim to ``python3 -c`` on the selected host. It has no
platform imports. A held root descriptor and O_NOFOLLOW on every component keep
renames and symlink replacement from escaping the service directory.
"""

import base64
import codecs
import json
import os
import re
import stat
import sys
import time
from collections import deque

MAX_BYTES = 1048576
MAX_FILES = 1000
MAX_DOWNLOAD = 104857600


class LogError(Exception):
    pass


def leaf(name):
    if (
        not isinstance(name, str)
        or not name
        or name in (".", "..")
        or "/" in name
        or "\x00" in name
        or len(name.encode("utf8")) > 255
    ):
        raise LogError("invalid_file")
    return name


def _error(exc):
    if isinstance(exc, PermissionError):
        return LogError("permission_denied")
    if isinstance(exc, FileNotFoundError):
        return LogError("file_missing")
    return LogError("file_unavailable")


class PlainText:
    """Incremental UTF-8 and terminal-control remover, including split OSC/CSI."""

    def __init__(self):
        self.decoder = codecs.getincrementaldecoder("utf8")("replace")
        self.state = "text"

    def feed(self, data, final=False):
        result = []
        for char in self.decoder.decode(data, final=final):
            n = ord(char)
            if self.state == "osc":
                if char == "\x07" or char == "\x9c":
                    self.state = "text"
                elif char == "\x1b":
                    self.state = "osc_escape"
                continue
            if self.state == "osc_escape":
                self.state = "text" if char == "\\" else "osc"
                continue
            if self.state == "csi":
                if 0x40 <= n <= 0x7E:
                    self.state = "text"
                continue
            if self.state == "escape":
                self.state = (
                    "csi" if char == "[" else ("osc" if char in "]PX^_" else "text")
                )
                continue
            if char == "\x1b":
                self.state = "escape"
            elif char == "\x9b":
                self.state = "csi"
            elif char in ("\x9d", "\x90", "\x98", "\x9e", "\x9f"):
                self.state = "osc"
            elif char in "\n\r\t" or n >= 32 and not 0x7F <= n <= 0x9F:
                result.append(char)
        return "".join(result)


class LogRoot:
    def __init__(self, path):
        if not isinstance(path, str) or not path.startswith("/") or "\x00" in path:
            raise LogError("invalid_directory")
        self.path = os.path.realpath(path)
        self.fd = None
        # realpath is only canonicalization: do not subsequently follow any
        # symlink in that result. If an ancestor races, fail closed.
        current = os.open("/", os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
        try:
            for component in self.path.split("/"):
                if component:
                    nxt = os.open(
                        component,
                        os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
                        dir_fd=current,
                    )
                    os.close(current)
                    current = nxt
            self.fd = current
        except OSError as exc:
            os.close(current)
            raise _error(exc) from None

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def close(self):
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None

    def open_file(self, name):
        leaf(name)
        pending = deque([name])
        directories = [os.dup(self.fd)]
        links = 0
        try:
            while pending:
                part = pending.popleft()
                if part in ("", "."):
                    continue
                if part == "..":
                    if len(directories) == 1:
                        raise LogError("path_escape")
                    os.close(directories.pop())
                    continue
                # O_PATH pins the symlink itself, so readlink cannot race its
                # replacement. Reopening our own FD pins the same regular inode.
                handle = os.open(
                    part,
                    os.O_PATH | os.O_NOFOLLOW | os.O_CLOEXEC,
                    dir_fd=directories[-1],
                )
                try:
                    info = os.fstat(handle)
                    if stat.S_ISLNK(info.st_mode):
                        links += 1
                        if links > 40:
                            raise LogError("path_escape")
                        destination = os.readlink("", dir_fd=handle)
                        if destination.startswith("/"):
                            prefix = self.path.rstrip("/") + "/"
                            if not destination.startswith(prefix):
                                raise LogError("path_escape")
                            destination = destination[len(prefix) :]
                            while len(directories) > 1:
                                os.close(directories.pop())
                        pending.extendleft(reversed(destination.split("/")))
                    elif pending:
                        if not stat.S_ISDIR(info.st_mode):
                            raise LogError("invalid_file")
                        directories.append(handle)
                        handle = None
                    else:
                        if not stat.S_ISREG(info.st_mode):
                            raise LogError("invalid_file")
                        return os.open(
                            "/proc/self/fd/" + str(handle),
                            os.O_RDONLY | os.O_NONBLOCK | os.O_CLOEXEC,
                        )
                finally:
                    if handle is not None:
                        os.close(handle)
            raise LogError("invalid_file")
        except OSError as exc:
            raise _error(exc) from None
        finally:
            for directory in directories:
                os.close(directory)

    def list_files(self):
        files = []
        truncated = False
        # Bound examined entries as well as returned entries, including a
        # directory containing millions of unsafe names or subdirectories.
        with os.scandir(self.fd) as entries:
            for index, entry in enumerate(entries):
                if index >= MAX_FILES:
                    truncated = True
                    break
                try:
                    fd = self.open_file(entry.name)
                    try:
                        info = os.fstat(fd)
                        files.append(
                            {
                                "name": entry.name,
                                "size": info.st_size,
                                "mtime": info.st_mtime,
                            }
                        )
                    finally:
                        os.close(fd)
                except LogError:
                    continue
        files.sort(key=lambda item: (-item["mtime"], item["name"]))
        return {"type": "files", "files": files, "truncated": truncated}

    def search(self, keyword, case_sensitive=False, progress=None):
        if not isinstance(keyword, str) or not keyword.strip() or len(keyword) > 200 or "\x00" in keyword:
            raise LogError("invalid_keyword")
        if type(case_sensitive) is not bool:
            raise LogError("invalid_request")
        needle = keyword if case_sensitive else keyword.casefold()
        result = {"type": "search", "hits": [], "scanned_files": 0,
                  "scanned_bytes": 0, "skipped_files": 0, "truncated": False,
                  "reason": None}
        deadline = time.monotonic() + 20
        with os.scandir(self.fd) as entries:
            for index, entry in enumerate(entries):
                if index >= MAX_FILES:
                    result.update(truncated=True, reason="directory_limit")
                    break
                name = entry.name
                if name.lower().endswith((".gz", ".zip", ".bz2", ".xz", ".zst")):
                    result["skipped_files"] += 1
                    continue
                if not (re.search(r"\.log(?:[.-].+)?$", name, re.I)
                        or re.search(r"\.(?:INFO|WARNING|ERROR|FATAL)(?:\.|$)", name)
                        or name.lower() in ("stdout", "stderr", "launcher.log")):
                    continue
                if result["scanned_files"] >= 200 or result["scanned_bytes"] >= 16 * MAX_BYTES or time.monotonic() >= deadline:
                    result.update(truncated=True, reason="scan_limit")
                    break
                try:
                    fd = self.open_file(name)
                except (LogError, OSError):
                    result["skipped_files"] += 1
                    continue
                try:
                    size = os.fstat(fd).st_size
                    remaining = 16 * MAX_BYTES - result["scanned_bytes"]
                    count = min(size, MAX_BYTES, remaining)
                    data = os.pread(fd, count, 0)
                except OSError:
                    result["skipped_files"] += 1
                    continue
                finally:
                    os.close(fd)
                if b"\x00" in data:
                    result["skipped_files"] += 1
                    continue
                result["scanned_files"] += 1
                result["scanned_bytes"] += len(data)
                if progress and result["scanned_files"] % 5 == 0:
                    progress({"type": "search_progress", "scanned_files": result["scanned_files"], "scanned_bytes": result["scanned_bytes"], "hits": len(result["hits"])})
                if size > len(data):
                    result.update(truncated=True, reason="file_limit")
                lines = PlainText().feed(data, final=True).splitlines()
                if size > len(data) and lines:
                    lines.pop()  # Last line may be incomplete.
                for line_no, line in enumerate(lines, 1):
                    if time.monotonic() >= deadline:
                        result.update(truncated=True, reason="time_limit")
                        break
                    if needle in (line if case_sensitive else line.casefold()):
                        result["hits"].append({"name": name, "line": line_no,
                            "text": line[:4000],
                            "before": [part[:4000] for part in lines[max(0, line_no - 3):line_no - 1]],
                            "after": [part[:4000] for part in lines[line_no:line_no + 2]]})
                        if len(result["hits"]) >= 200:
                            result.update(truncated=True, reason="match_limit")
                            break
                if result["reason"] in ("match_limit", "time_limit"):
                    break
        return result

    def _read(self, name, lines, cursor, decoder, final):
        if type(lines) is not int or not 1 <= lines <= 1000:
            raise LogError("invalid_lines")
        fd = self.open_file(name)
        try:
            info = os.fstat(fd)
            identity = {"device": info.st_dev, "inode": info.st_ino}
            valid = cursor is not None and all(
                type(cursor.get(k)) is int and cursor[k] >= 0
                for k in ("device", "inode", "offset")
            )
            resume = (
                valid
                and all(cursor[k] == identity[k] for k in identity)
                and cursor["offset"] <= info.st_size
            )
            reset = cursor is not None and not resume
            if reset:
                decoder = PlainText()
            if resume:
                start = cursor["offset"]
                size = min(MAX_BYTES, info.st_size - start)
            else:
                start = max(0, info.st_size - MAX_BYTES)
                size = min(MAX_BYTES, info.st_size)
            data = os.pread(fd, size, start)
            end = start + len(data)
            truncated = (not resume and start > 0) or (
                resume and start + len(data) < info.st_size
            )
            if not resume:
                pieces = data.splitlines(keepends=True)
                if len(pieces) > lines:
                    data = b"".join(pieces[-lines:])
                    truncated = True
            text = decoder.feed(data, final=final)
            encoded = text.encode("utf8")
            if len(encoded) > MAX_BYTES:
                text = encoded[-MAX_BYTES:].decode("utf8", errors="ignore")
                truncated = True
            event = {
                "type": "text",
                "text": text,
                "cursor": dict(identity, offset=end),
                "reset": reset,
                "truncated": truncated,
            }
            return event, decoder
        finally:
            os.close(fd)

    def read(self, name, lines=500, cursor=None):
        return self._read(name, lines, cursor, PlainText(), True)[0]

    def follow(self, name, lines=500, cursor=None, interval=0.2):
        decoder = PlainText()
        first = True
        while True:
            event, decoder = self._read(name, lines, cursor, decoder, False)
            if first or event["cursor"] != cursor or event["reset"]:
                yield event
                first = False
            cursor = event["cursor"]
            time.sleep(interval)

    def download(self, name, max_bytes=MAX_DOWNLOAD):
        fd = self.open_file(name)
        try:
            size = os.fstat(fd).st_size
            if size > min(max_bytes, MAX_DOWNLOAD):
                raise LogError("download_too_large")
            yield {"type": "download_start", "name": name, "size": size}
            offset = 0
            while offset < size:
                data = os.pread(fd, min(65536, size - offset), offset)
                if not data:
                    raise LogError("file_truncated")
                offset += len(data)
                yield {"type": "download_chunk", "data": data}
        finally:
            os.close(fd)


def main(parameters):
    def emit(event):
        if event.get("type") == "download_chunk":
            event = dict(event, data=base64.b64encode(event["data"]).decode("ascii"))
        print(json.dumps(event, ensure_ascii=True), flush=True)

    try:
        with LogRoot(parameters["root"]) as logs:
            emit({"type": "ready"})
            kind = parameters["kind"]
            if kind == "files":
                emit(logs.list_files())
            elif kind == "search":
                emit(logs.search(parameters.get("keyword"), parameters.get("case_sensitive", False), emit))
            elif kind == "read":
                emit(
                    logs.read(
                        parameters["name"],
                        parameters.get("lines", 500),
                        parameters.get("cursor"),
                    )
                )
            elif kind == "download":
                for event in logs.download(
                    parameters["name"], parameters.get("max_download", MAX_DOWNLOAD)
                ):
                    emit(event)
            elif kind == "log-follow":
                for event in logs.follow(
                    parameters["name"],
                    parameters.get("lines", 500),
                    parameters.get("cursor"),
                ):
                    emit(event)
            else:
                raise LogError("invalid_request")
        emit({"type": "done"})
    except (LogError, OSError) as exc:
        emit(
            {
                "type": "error",
                "code": str(exc) if isinstance(exc, LogError) else str(_error(exc)),
            }
        )


if __name__ == "__main__":
    main(json.loads(sys.argv[1]))
