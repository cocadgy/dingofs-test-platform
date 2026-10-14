"""Run on the source host. Credentials arrive over SSH stdin, never argv."""
import fcntl
import termios
import json
import os
from pathlib import Path
import pty
import re
import select
import shlex
import shutil
import signal
import subprocess
import sys
import tempfile
import time

request = json.load(sys.stdin)
scp = shutil.which('scp')
if not scp:
    raise RuntimeError('平台来源机器未安装 scp，请安装 openssh-clients')
host = request['host']
if not re.fullmatch(r'[A-Za-z0-9_.:-]+', host) or host.startswith('-'):
    raise ValueError('无效的目标主机地址')
if ':' in host:
    host = '[' + host + ']'
with tempfile.TemporaryDirectory(prefix='dpt-scp-') as directory:
    root = Path(directory)
    password = root/'password'
    password.write_text(request['password'])
    password.chmod(0o600)
    askpass = root/'askpass'
    askpass.write_text('#!/bin/sh\ncat ' + shlex.quote(str(password)) + '\n')
    askpass.chmod(0o700)
    argv = [scp, '-P', str(request['port']), '-o', 'User='+request['username'],
            '-o', 'StrictHostKeyChecking=accept-new', '-o', 'UserKnownHostsFile='+str(root/'known_hosts'),
            '-o', 'ConnectTimeout=15', '-o', 'ServerAliveInterval=15', '-o', 'ServerAliveCountMax=3',
            '-o', 'NumberOfPasswordPrompts=1', '--', request['source'], host+':'+request['destination']]
    print('$ ' + shlex.join(argv), flush=True)
    env = dict(os.environ, SSH_ASKPASS=str(askpass), SSH_ASKPASS_REQUIRE='force', DISPLAY='dpt:0')
    master, slave = pty.openpty()
    process = None
    tail = ''
    deadline = time.monotonic() + request['timeout']
    try:
        def terminal_session():
            os.setsid()
            fcntl.ioctl(slave, termios.TIOCSCTTY, 0)
        process = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=slave, stderr=slave,
                                   env=env, preexec_fn=terminal_session)
        os.close(slave)
        slave = None
        while True:
            if time.monotonic() >= deadline:
                raise TimeoutError('SCP 传输超时')
            if select.select([master], [], [], .2)[0]:
                try:
                    data = os.read(master, 8192)
                except OSError:
                    data = b''
                if not data:
                    break
                text = data.decode(errors='replace').replace('\r', '\n')
                if request['password']:
                    text = text.replace(request['password'], '[REDACTED]')
                tail = (tail + text)[-8000:]
                print(text, end='', flush=True)
            elif process.poll() is not None:
                break
        rc = process.wait(timeout=max(.1, deadline-time.monotonic()))
        if rc:
            raise RuntimeError('SCP 传输失败 (exit '+str(rc)+'): '+tail)
        print(json.dumps({'success': True}), flush=True)
    finally:
        if process is not None and process.poll() is None:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait()
        os.close(master)
        if slave is not None:
            os.close(slave)
