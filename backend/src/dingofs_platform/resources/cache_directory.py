"""Prepare cache bases without changing existing directory permissions."""
import os
import pwd
import subprocess

# Fixed code bundled into the remote command, never loaded from a writable
# file when escalating. Only mkdir/ownership of freshly created bases is elevated.
DIRECTORY_CODE = r'''
import ctypes
import os
import secrets

def create_directory(path, uid, gid):
    if not isinstance(path, str) or not path.startswith('/') or path == '/' or '\x00' in path:
        raise ValueError('invalid cache base directory')
    parts = path.split('/')[1:]
    if any(p in ('', '.', '..') for p in parts):
        raise ValueError('invalid cache base directory')
    flags = os.O_PATH | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
    fd = os.open('/', flags)
    staging = {}
    try:
        for index, part in enumerate(parts):
            info = os.fstat(fd)
            # Protected same-filesystem ancestors anchor directory provenance.
            if (info.st_uid == os.geteuid() and not info.st_mode & 0o022) or (info.st_uid in (0, os.geteuid()) and info.st_mode & 0o1000):
                old = staging.get(info.st_dev)
                if old is not None:
                    os.close(old)
                staging[info.st_dev] = os.dup(fd)
            final = index == len(parts) - 1
            try:
                child = os.open(part, flags, dir_fd=fd)
            except FileNotFoundError:
                if not final:
                    try:
                        os.mkdir(part, 0o755, dir_fd=fd)
                    except FileExistsError:
                        pass
                    child = os.open(part, flags, dir_fd=fd)
                else:
                    stage_fd = staging.get(os.fstat(fd).st_dev)
                    if stage_fd is None:
                        if os.geteuid() != 0:
                            raise PermissionError('privileged directory preparation required')
                        raise ValueError('没有可安全创建缓存目录的同文件系统父目录，请管理员预先创建')
                    temporary = '.dtt-cache-' + secrets.token_hex(16)
                    os.mkdir(temporary, 0o700, dir_fd=stage_fd)
                    child = os.open(temporary, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=stage_fd)
                    published = False
                    try:
                        libc = ctypes.CDLL(None, use_errno=True)
                        rename = libc.renameat2
                        rename.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
                        rename.restype = ctypes.c_int
                        if rename(stage_fd, os.fsencode(temporary), fd, os.fsencode(part), 1):
                            number = ctypes.get_errno()
                            raise OSError(number, os.strerror(number), path)
                        published = True
                        if os.geteuid() == 0:
                            os.fchown(child, uid, gid)
                        os.fchmod(child, 0o750)
                        actual, opened = os.stat(part, dir_fd=fd, follow_symlinks=False), os.fstat(child)
                        if (actual.st_dev, actual.st_ino) != (opened.st_dev, opened.st_ino):
                            raise ValueError('cache directory changed during creation')
                    except BaseException:
                        if not published:
                            actual, opened = os.stat(temporary, dir_fd=stage_fd, follow_symlinks=False), os.fstat(child)
                            if (actual.st_dev, actual.st_ino) == (opened.st_dev, opened.st_ino):
                                os.rmdir(temporary, dir_fd=stage_fd)
                        os.close(child)
                        raise
            os.close(fd)
            fd = child
    finally:
        os.close(fd)
        for stage_fd in staging.values():
            os.close(stage_fd)
'''
exec(DIRECTORY_CODE)


def prepare_cache_directory(path):
    uid = os.geteuid()
    gid = pwd.getpwuid(uid).pw_gid
    try:
        create_directory(path, uid, gid)
    except PermissionError:
        try:
            os.lstat(path)
        except FileNotFoundError:
            pass
        except PermissionError:
            raise ValueError("无法确认缓存基础目录是否存在，请管理员检查父目录权限：" + path) from None
        else:
            raise ValueError("已有缓存基础目录权限不足，请管理员授权：" + path) from None
        script = DIRECTORY_CODE + '\nimport sys, pwd\nuid=int(sys.argv[2])\nassert uid == int(os.environ.get("SUDO_UID", "-1"))\ncreate_directory(sys.argv[1], uid, pwd.getpwuid(uid).pw_gid)\n'
        try:
            result = subprocess.run(
                ["sudo", "-n", "--", "/usr/bin/python3", "-I", "-c", script, path, str(uid)],
                stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=30,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise ValueError("sudo 创建缓存基础目录失败，请管理员检查 sudo 授权或手动创建：" + path) from exc
        if result.returncode:
            raise ValueError("sudo 创建缓存基础目录失败（需要免密 sudo 授权），请管理员检查路径或手动创建：" + path)
    fd = os.open('/', os.O_PATH | os.O_DIRECTORY)
    try:
        for part in path.split('/')[1:]:
            child = os.open(part, os.O_PATH | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = child
        if not os.access('/proc/self/fd/' + str(fd), os.R_OK | os.W_OK | os.X_OK):
            raise ValueError("缓存基础目录读写或进入权限不足：" + path)
    finally:
        os.close(fd)
