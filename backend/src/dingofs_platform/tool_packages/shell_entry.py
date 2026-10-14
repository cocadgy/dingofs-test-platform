"""Install user-level dtt commands; preserve previous commands and shell settings."""


def install_shell_entry(home):
    import os
    import re
    import shlex
    import shutil
    import stat
    import tempfile
    from pathlib import Path
    from uuid import uuid4

    home = Path(home)
    bindir = home / '.local/bin'
    bindir.mkdir(parents=True, exist_ok=True)
    command = home / '.local/share/dingofs-platform/tools/dtt/current/dtt'
    launcher = '#!/bin/sh\n# Managed by DingoFS test platform\nexec ' + shlex.quote(str(command)) + ' "$@"\n'
    backups = []

    def replace(path, content, mode, follow=False):
        target = path.resolve() if follow and path.is_symlink() else path
        if target.exists() and target.is_dir():
            raise RuntimeError('命令或 shell 配置路径是目录：' + str(target))
        if target.is_file() and (follow or not target.is_symlink()) and target.read_bytes() == content.encode():
            os.chmod(target, mode)
            return
        if target.exists() or target.is_symlink():
            backup = target.with_name(target.name + '.before-platform-' + uuid4().hex[:12])
            shutil.copy2(target, backup, follow_symlinks=False)
            backups.append(str(backup))
        fd, temporary = tempfile.mkstemp(prefix='.' + target.name + '-', dir=target.parent)
        try:
            with os.fdopen(fd, 'w') as stream:
                stream.write(content)
            os.chmod(temporary, mode)
            os.replace(temporary, target)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    for name in ('dtt', 'dingofs-testsuite-tool'):
        replace(bindir / name, launcher, 0o755)

    begin, end = '# BEGIN DINGOFS PLATFORM DTT', '# END DINGOFS PLATFORM DTT'
    block = '\n'.join((begin,
        'case "$PATH" in',
        '  "$HOME/.local/bin"|"$HOME/.local/bin":*) ;;',
        '  *) export PATH="$HOME/.local/bin:$PATH" ;;',
        'esac',
        'unalias dtt dingofs-testsuite-tool 2>/dev/null || :',
        'unset -f dtt dingofs-testsuite-tool 2>/dev/null || :',
        'hash -r 2>/dev/null || :', end))
    # Respect Bash's login-file precedence; do not shadow an existing .profile.
    login = next((home / name for name in ('.bash_profile', '.bash_login', '.profile') if (home / name).exists()), home / '.profile')
    profiles = [home / '.bashrc', login, home / '.zshrc', home / '.zprofile']
    for path in profiles:
        old = path.read_text() if path.exists() else ''
        if begin in old and end not in old:
            raise RuntimeError('shell 配置中的平台标记不完整，请检查：' + str(path))
        cleaned = re.sub(re.escape(begin) + r'.*?' + re.escape(end), '', old, flags=re.S).rstrip('\n')
        updated = cleaned + ('\n\n' if cleaned else '') + block + '\n'
        mode = stat.S_IMODE(path.stat().st_mode) if path.exists() else 0o644
        replace(path, updated, mode, follow=True)
    return {'command_path': str(bindir / 'dtt'), 'shell_profiles': [str(path) for path in profiles], 'backups': backups}
