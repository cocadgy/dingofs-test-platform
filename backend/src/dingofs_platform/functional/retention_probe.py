"""Standalone read-only identity probe sent over the authorized frozen SSH route."""
import json
import os
from pathlib import Path
import pwd
import stat
import subprocess


def query(argv):
    result = subprocess.run(argv, capture_output=True, text=True, timeout=20)
    if result.returncode or len(result.stdout) + len(result.stderr) > 1024 * 1024:
        raise ValueError('query failed')
    return json.loads(result.stdout)


def filesystem_identity(request):
    value = query([request['dingo'], 'fs', 'list', '--mdsaddr', request['target']['cluster'], '--format', 'json'])
    while isinstance(value, dict):
        keys = [key for key in ('result', 'fs_infos', 'fsInfos', 'filesystems') if key in value]
        if len(keys) != 1:
            raise ValueError('unrecognized filesystem schema')
        value = value[keys[0]]
    if not isinstance(value, list):
        raise ValueError('unrecognized filesystem schema')
    rows = []
    for row in value:
        names = [row[key] for key in ('fs_name', 'fsname', 'fsName') if key in row]
        ids = [row[key] for key in ('fs_id', 'fsId', 'id') if key in row]
        if len(names) != 1 or len(ids) != 1 or not isinstance(names[0], str) or not names[0] or not str(ids[0]).isdigit():
            raise ValueError('incomplete filesystem identity')
        rows.append((names[0], str(ids[0])))
    if len({name for name, _ in rows}) != len(rows) or len({ident for _, ident in rows}) != len(rows):
        raise ValueError('ambiguous filesystem identity')
    found = [ident for name, ident in rows if name == request['target']['name']]
    return {'fs_id': found[0]} if found else None


def directory_identity(path):
    path = Path(path)
    if not path.is_absolute() or '..' in path.parts or path == Path('/'):
        raise ValueError('unsafe path')
    current = os.open('/', os.O_RDONLY | os.O_DIRECTORY)
    try:
        for part in path.parts[1:]:
            try:
                following = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=current)
            except FileNotFoundError:
                return None
            os.close(current)
            current = following
        info = os.fstat(current)
        return {'device_inode': f'{info.st_dev}:{info.st_ino}'}
    finally:
        os.close(current)


def option_values(argv, names):
    values = []
    for i, arg in enumerate(argv):
        if arg in names:
            values.append(argv[i + 1])
        for name in names:
            if arg.startswith(name + '='):
                values.append(arg[len(name) + 1:])
    return values


def processes(kind, target):
    found = []
    for entry in Path('/proc').iterdir():
        if not entry.name.isdigit():
            continue
        try:
            argv = [p.decode() for p in (entry / 'cmdline').read_bytes().split(b'\0') if p]
            if not argv or Path(argv[0]).name != ('dingo-client' if kind == 'mount' else 'dingo-cache'):
                continue
            if kind == 'cache':
                match = option_values(argv, ('--id',)) == [target['name']]
            else:
                paths = option_values(argv, ('--mountpoint', '--mount_point'))
                match = paths == [target['path']] or target['path'] in argv[1:]
            if not match:
                continue
            if pwd.getpwuid(entry.stat().st_uid).pw_name != target['user']:
                raise ValueError('process owner changed')
            before = (entry / 'stat').read_text().rsplit(')', 1)[1].split()
            exe = os.readlink(entry / 'exe').removesuffix(' (deleted)')
            if Path(exe).name != ('dingo-client' if kind == 'mount' else 'dingo-cache'):
                raise ValueError('process executable changed')
            after = (entry / 'stat').read_text().rsplit(')', 1)[1].split()
            if before[19] != after[19] or after[0] == 'Z':
                raise ValueError('unstable process identity')
            if kind == 'cache':
                found.append({'pid': int(entry.name), 'start': after[19], 'exe': exe, 'member_id': target['name']})
            else:
                if not paths:
                    paths = [arg for i, arg in enumerate(argv[1:], 1) if arg == target['path'] and
                             (i == 1 or not argv[i - 1].startswith('-') or '=' in argv[i - 1])]
                names = option_values(argv, ('--fs_name', '--fsname'))
                addresses = option_values(argv, ('--mds_addr', '--mdsaddr'))
                for arg in argv:
                    if arg.startswith('mds://'):
                        address, _, name = arg[6:].rpartition('/')
                        names.append(name)
                        addresses.append(address)
                if paths != [target['path']] or set(names) != {target['name']} or set(addresses) != {target['cluster']}:
                    raise ValueError('mount process target changed')
                found.append({'pid': int(entry.name), 'start_time': after[19], 'exe': exe,
                    'fs_name': target['name'], 'mds_addr': target['cluster'], 'mount_path': target['path']})
        except (FileNotFoundError, ProcessLookupError):
            continue
    return found


def mount_identity(request):
    target = request['target']
    result = subprocess.run(['findmnt', '--json', '--mountpoint', target['path'], '--output', 'ID,TARGET,SOURCE,FSTYPE'],
                            capture_output=True, text=True, timeout=20)
    current = processes('mount', target)
    if result.returncode == 1 and not result.stdout.strip() and not result.stderr.strip() and not current:
        return None
    if result.returncode or len(result.stdout) > 1024 * 1024:
        raise ValueError('mount query failed')
    rows = json.loads(result.stdout)['filesystems']
    if len(rows) != 1 or len(current) != 1 or rows[0]['target'] != target['path']:
        raise ValueError('ambiguous mount')
    row = rows[0]
    if (row['source'] not in ('DingoFS:' + target['name'], 'mds://' + target['cluster'] + '/' + target['name'])
            or row['fstype'] not in ('fuse.dingofs', 'fuse.dingo') or not row['id']):
        raise ValueError('mount source changed')
    return {key: row[key] for key in ('id', 'target', 'source', 'fstype')} | {'process': current[0]}


def cache_registration(request):
    target = request['target']
    data = query([request['dingo'], 'cache', 'member', 'list', '--mdsaddr', target['cluster'], '--format', 'json'])
    rows = data['result']['members']
    if not isinstance(rows, list) or any(not isinstance(row, dict) or not row.get('member_id') for row in rows):
        raise ValueError('cache schema')
    if len({row['member_id'] for row in rows}) != len(rows):
        raise ValueError('duplicate cache members')
    return {'members': rows}


def cache_identity(request):
    target = request['target']
    registration = request['registration'] if 'registration' in request else cache_registration(request)
    rows = registration['members']
    if not isinstance(rows, list) or any(not isinstance(row, dict) or not row.get('member_id') for row in rows):
        raise ValueError('cache schema')
    matches = [row for row in rows if row['member_id'] == target['name']]
    current = processes('cache', target)
    if not matches and not current:
        return None
    if len(matches) != 1 or len(current) > 1:
        raise ValueError('ambiguous cache')
    row = matches[0]
    return {'member_id': row['member_id'], 'group_name': row['group_name'], 'ip': row['ip'],
            'port': int(row['port']), 'process': current[0] if current else None}


def original_process_alive(request):
    expected = request['expected_identity'].get('process') or {}
    if not expected:
        return False
    if type(expected.get('pid')) is not int or expected['pid'] <= 0:
        raise ValueError('invalid original process')
    start = expected.get('start_time') if request['kind'] == 'mount' else expected.get('start')
    if not isinstance(start, str) or not start.isdigit():
        raise ValueError('invalid original start time')
    try:
        fields = (Path('/proc') / str(expected['pid']) / 'stat').read_text().rsplit(')', 1)[1].split()
        return fields[19] == start and fields[0] != 'Z'
    except (FileNotFoundError, ProcessLookupError):
        return False


def probe(request):
    response = {key: request[key] for key in ('child_id', 'resource_id', 'kind', 'expected_identity', 'target')}
    response.update(status='unknown', identity=None)
    try:
        if request['kind'] == 'directory' and not request['expected_identity'].get('filesystem_relative'):
            identity = directory_identity(request['target']['path'])
        elif request['kind'] == 'filesystem':
            identity = filesystem_identity(request)
        elif request['kind'] == 'mount':
            identity = mount_identity(request)
            response['namespace'] = os.readlink('/proc/self/ns/mnt')
            response['boot_id'] = Path('/proc/sys/kernel/random/boot_id').read_text().strip()
            if identity is None:
                if request.get('mount_scope') != {key: response[key] for key in ('namespace', 'boot_id')}:
                    raise ValueError('original mount namespace is unverified')
            else:
                response['process_namespace'] = os.readlink('/proc/' + str(identity['process']['pid']) + '/ns/mnt')
                if response['process_namespace'] != response['namespace']:
                    raise ValueError('mount process namespace changed')
        elif request['kind'] == 'cache':
            identity = cache_identity(request)
        else:
            return response
        if (request['kind'] in ('mount', 'cache') and (identity is None or identity.get('process') is None)
                and original_process_alive(request)):
            raise ValueError('original process still alive')
        response.update(status='absent' if identity is None else 'present', identity=identity)
    except Exception:
        pass  # Never return raw remote output, errors or possible credentials.
    return response
