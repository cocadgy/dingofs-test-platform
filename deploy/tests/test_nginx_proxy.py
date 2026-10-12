"""Real Nginx routing regression; run explicitly, requires local Docker image.

PLATFORM_TEST_WEB_IMAGE=dingofs-test-platform-web:latest python3 -m unittest discover -s deploy/tests -v
Uses an ephemeral loopback echo upstream and an isolated Nginx container.
"""

import http.client
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import socket
import subprocess
import tempfile
import threading
import time
import unittest
import uuid


@unittest.skipUnless(
    os.environ.get("PLATFORM_TEST_WEB_IMAGE"),
    "explicit local proxy test opt-in required",
)
class NginxProxyTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        class Echo(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def do_GET(self):
                if self.headers.get("Upgrade") == "websocket":
                    self.send_response(101)
                    self.send_header("Upgrade", "websocket")
                    self.send_header("Connection", "Upgrade")
                    self.end_headers()
                    return
                self.respond()

            def do_POST(self):
                self.respond()

            def respond(self):
                body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
                result = json.dumps(
                    {
                        "method": self.command,
                        "path": self.path,
                        "body": body.decode(),
                        "host": self.headers.get("Host"),
                        "csrf": self.headers.get("X-CSRF-Token"),
                    }
                ).encode()
                self.send_response(200)
                self.send_header("Content-Length", str(len(result)))
                self.end_headers()
                self.wfile.write(result)

            def log_message(self, *args):
                pass

        cls.upstream = ThreadingHTTPServer(("127.0.0.1", 0), Echo)
        cls.thread = threading.Thread(target=cls.upstream.serve_forever, daemon=True)
        cls.thread.start()
        listener = socket.socket()
        listener.bind(("127.0.0.1", 0))
        cls.port = listener.getsockname()[1]
        listener.close()
        cls.directory = tempfile.TemporaryDirectory(prefix="platform-proxy-test-")
        config = Path(
            os.environ.get(
                "PLATFORM_TEST_NGINX_CONFIG",
                Path(__file__).resolve().parents[1] / "nginx.conf",
            )
        ).read_text()
        config = config.replace(
            "listen 8080;", f"listen 127.0.0.1:{cls.port};"
        ).replace("http://api:8000", f"http://127.0.0.1:{cls.upstream.server_port}")
        path = Path(cls.directory.name) / "nginx.conf"
        path.write_text(config)
        path.chmod(0o644)
        cls.container = "platform-proxy-test-" + uuid.uuid4().hex[:10]
        try:
            subprocess.run(
                [
                    "docker",
                    "run",
                    "-d",
                    "--name",
                    cls.container,
                    "--network",
                    "host",
                    "--entrypoint",
                    "nginx",
                    "-v",
                    f"{path}:/etc/nginx/conf.d/default.conf:ro",
                    os.environ["PLATFORM_TEST_WEB_IMAGE"],
                    "-g",
                    "daemon off;",
                ],
                check=True,
                capture_output=True,
            )
            for _ in range(100):
                try:
                    with socket.create_connection(("127.0.0.1", cls.port), timeout=0.1):
                        break
                except OSError:
                    time.sleep(0.05)
            else:
                raise RuntimeError("Test Nginx failed to start")
        except BaseException:
            cls.tearDownClass()
            raise

    @classmethod
    def tearDownClass(cls):
        subprocess.run(["docker", "rm", "-f", cls.container], capture_output=True)
        cls.upstream.shutdown()
        cls.upstream.server_close()
        cls.thread.join(timeout=2)
        cls.directory.cleanup()

    def request(self, method, path, body=None, headers=None):
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        try:
            connection.request(
                method,
                path,
                body=body,
                headers={"Host": "platform.example:58080", **(headers or {})},
            )
            response = connection.getresponse()
            return response.status, dict(response.getheaders()), response.read()
        finally:
            connection.close()

    def test_create_preserves_post_body_and_external_host_without_redirect(self):
        status, headers, body = self.request(
            "POST",
            "/api/v1/remote-sessions",
            '{"kind":"files"}',
            {"Content-Type": "application/json", "X-CSRF-Token": "test-csrf"},
        )
        self.assertEqual(status, 200, headers)
        self.assertNotIn("Location", headers)
        self.assertEqual(
            json.loads(body),
            {
                "method": "POST",
                "path": "/api/v1/remote-sessions",
                "body": '{"kind":"files"}',
                "host": "platform.example:58080",
                "csrf": "test-csrf",
            },
        )

    def test_session_poll_is_proxied(self):
        status, _, body = self.request("GET", "/api/v1/remote-sessions/example")
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["path"], "/api/v1/remote-sessions/example")

    def test_websocket_upgrade_is_retained(self):
        status, headers, _ = self.request(
            "GET",
            "/api/v1/remote-sessions/example/stream",
            headers={"Upgrade": "websocket", "Connection": "Upgrade"},
        )
        self.assertEqual(status, 101)
        self.assertEqual(headers.get("Upgrade", "").lower(), "websocket")
