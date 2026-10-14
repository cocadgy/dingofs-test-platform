"""Real SSH/SFTP protocol on loopback; remote commands run in an isolated temp HOME."""
import hashlib
import json
import os
from pathlib import Path
import shlex
import socket
import subprocess
import threading
import time
import paramiko
from dingofs_platform.inventory.ssh_transport import SSHConfig
from dingofs_platform.tool_packages.transport import execute


def test_transfer_verify_activate_and_probe_over_ssh(tmp_path):
    home = tmp_path/'home'
    home.mkdir()
    source = tmp_path/'bundles'/'v1'
    source.mkdir(parents=True)
    binary = source/'dingo'
    binary.write_text('#!/bin/sh\necho dingo-test-v1\n')
    bundle = {'tool':'dingo','version':'v1','entrypoint':'dingo','architecture':__import__('platform').machine(),
              'directory':'v1','digest':'c'*64,'size_bytes':binary.stat().st_size,
              'files':{'dingo':hashlib.sha256(binary.read_bytes()).hexdigest()}}
    (source/'manifest.json').write_text(json.dumps(bundle))
    workers=[]

    class Server(paramiko.ServerInterface):
        def check_auth_password(self, username, password):
            return paramiko.AUTH_SUCCESSFUL if (username,password)==('tester','test-only') else paramiko.AUTH_FAILED
        def get_allowed_auths(self, username): return 'password'
        def check_channel_request(self, kind, chanid): return paramiko.OPEN_SUCCEEDED
        def check_channel_exec_request(self, channel, command):
            def task():
                # Emulate the login shell's HOME for our isolated test account.
                outer=shlex.split(command.decode())
                assert outer[:2]==['bash','-lc']
                p=subprocess.run(['bash','-c',outer[2]],env=dict(os.environ,HOME=str(home)),capture_output=True)
                if p.stdout: channel.sendall(p.stdout)
                if p.stderr: channel.sendall_stderr(p.stderr)
                channel.send_exit_status(p.returncode)
                channel.close()
            worker=threading.Thread(target=task,daemon=True)
            workers.append(worker);worker.start();return True

    class Files(paramiko.SFTPServerInterface):
        def safe(self, path):
            value=Path(path)
            assert value.resolve().is_relative_to(home.resolve())
            return value
        def stat(self, path):
            try:return paramiko.SFTPAttributes.from_stat(self.safe(path).stat())
            except OSError as exc:return paramiko.SFTPServer.convert_errno(exc.errno)
        def mkdir(self, path, attr):
            try:self.safe(path).mkdir();return paramiko.SFTP_OK
            except OSError as exc:return paramiko.SFTPServer.convert_errno(exc.errno)
        def open(self, path, flags, attr):
            try:
                fd=os.open(self.safe(path),flags,0o600)
                handle=paramiko.SFTPHandle(flags)
                handle.writefile=os.fdopen(fd,'wb')
                return handle
            except OSError as exc:return paramiko.SFTPServer.convert_errno(exc.errno)

    listener=socket.socket()
    listener.bind(('127.0.0.1',0));listener.listen(1)
    port=listener.getsockname()[1]
    stop=threading.Event()
    def serve():
        connection,_=listener.accept()
        transport=paramiko.Transport(connection)
        transport.add_server_key(paramiko.RSAKey.generate(2048))
        transport.set_subsystem_handler('sftp',paramiko.SFTPServer,Files)
        transport.start_server(server=Server())
        while not stop.wait(0.05) and transport.is_active():pass
        transport.close()
    server=threading.Thread(target=serve,daemon=True);server.start()
    progress=[]
    try:
        result=execute(SSHConfig('127.0.0.1',port,'tester','test-only'),bundle,str(source.parent),30,lambda **data:progress.append(data))
        assert result['installed_path'].endswith('/tools/dingo/current/dingo')
        tool=next(item for item in result['items'] if item['tool']=='dingo')
        assert tool['status']=='ready'
        assert tool['version']=='v1'
        assert any('SFTP dingo' in row.get('message','') for row in progress)
        assert (home/'.local/share/dingofs-platform/tools/dingo/current/dingo').is_file()
    finally:
        stop.set();listener.close();server.join(2)
        for worker in workers:worker.join(2)
