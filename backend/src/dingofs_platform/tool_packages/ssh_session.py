"""Bounded SSH sessions shared by automatic pull and platform transfer."""
import json
import re
import shlex
import socket
import threading
import time
import paramiko


class Remote:
    def __init__(self, config, deadline, report, label):
        self.deadline, self.report, self.label = deadline, report, label
        self.client = paramiko.SSHClient()
        self.client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        self.timer = None
        if deadline is not None:
            self.timer = threading.Timer(self.remaining(), self.client.close)
            self.timer.daemon = True
            self.timer.start()
        try:
            self.client.connect(config.host, port=config.port, username=config.username, password=config.password,
                allow_agent=False, look_for_keys=False, timeout=min(15,self.remaining()),
                banner_timeout=min(15,self.remaining()), auth_timeout=min(15,self.remaining()))
            sock = self.client.get_transport().sock
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
            for name, value in (('TCP_KEEPIDLE', 15), ('TCP_KEEPINTVL', 15),
                                ('TCP_KEEPCNT', 3), ('TCP_USER_TIMEOUT', 60000)):
                if hasattr(socket, name):
                    sock.setsockopt(socket.IPPROTO_TCP, getattr(socket, name), value)
        except Exception:
            self.close()
            raise

    def remaining(self):
        if self.deadline is None:
            return float('inf')
        left = self.deadline-time.monotonic()
        if left <= 0:
            raise TimeoutError('工具部署超时，请检查任务日志')
        return left

    def close(self):
        if self.timer is not None:
            self.timer.cancel()
        self.client.close()

    def check_connection(self):
        """Bound only an SSH heartbeat, never the remote operation duration."""
        transport = self.client.get_transport()
        if transport is None or not transport.is_active():
            raise ConnectionError('工具部署 SSH 连接已断开')
        watchdog = threading.Timer(30, self.client.close)
        watchdog.daemon = True
        watchdog.start()
        try:
            # Either success or SSH_REQUEST_FAILURE is a valid liveness reply.
            transport.global_request('keepalive@openssh.com', wait=True)
            if not transport.is_active():
                raise ConnectionError('工具部署 SSH 连接未响应')
        finally:
            watchdog.cancel()

    def python(self, code, phase, input_data=None, progress_range=None, max_bytes=1024*1024):
        self.report(phase=phase, message=f'[{self.label}] {phase}\n')
        command='python3 -u -c '+shlex.quote(code)
        if self.deadline is not None:
            command='timeout --signal=TERM --kill-after=10s '+str(max(1,int(self.remaining())-10))+'s '+command
        channel=self.client.get_transport().open_session(timeout=min(15,self.remaining()))
        stdout, stderr=bytearray(),bytearray()
        try:
            channel.exec_command('bash -lc '+shlex.quote(command))
            if input_data is not None:
                channel.sendall(json.dumps(input_data).encode())
            channel.shutdown_write()
            last_probe=time.monotonic()
            while True:
                self.remaining()
                if not self.client.get_transport() or not self.client.get_transport().is_active():
                    raise ConnectionError('工具部署 SSH 连接已断开')
                if time.monotonic()-last_probe >= 15:
                    self.check_connection()
                    last_probe=time.monotonic()
                ready=False
                for available,read,buffer in ((channel.recv_ready,channel.recv,stdout),(channel.recv_stderr_ready,channel.recv_stderr,stderr)):
                    if available():
                        chunk=read(16384);buffer.extend(chunk)
                        if len(buffer)>max_bytes:del buffer[:-max_bytes]
                        text=chunk.decode(errors='replace')
                        self.report(message=text)
                        if progress_range:
                            matches=re.findall(r'(\d{1,3})%',text)
                            if matches:
                                fraction=min(100,int(matches[-1]))/100
                                start,end=progress_range
                                self.report(progress=int(start+(end-start)*fraction))
                        ready=True
                if channel.exit_status_ready() and not channel.recv_ready() and not channel.recv_stderr_ready():break
                if not ready:time.sleep(.05)
            if channel.recv_exit_status()!=0:
                raise RuntimeError(self.label+'：'+(stderr or stdout).decode(errors='replace')[-4000:])
            return json.loads(stdout.decode().strip().splitlines()[-1])
        finally:
            channel.close()

    def sftp(self):
        self.remaining()
        result=self.client.open_sftp()
        result.get_channel().settimeout(min(30,self.remaining()))
        return result
