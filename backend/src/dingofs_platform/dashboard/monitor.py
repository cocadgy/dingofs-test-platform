"""Bounded background probes. Results are process-local and contain no credentials."""

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from threading import Event, Lock, Thread
import time

from sqlalchemy import select

from dingofs_platform.clusters.parser import ClusterParseError, parse_cluster_status
from dingofs_platform.clusters.transport import (
    AuthenticationRequired,
    ClusterCommand,
    ClusterExecutionError,
    execute_cluster,
)
from dingofs_platform.errors import Problem
from dingofs_platform.dashboard.usage import SAMPLE_COMMAND, parse_usage
from dingofs_platform.inventory.credentials import decrypt_password
from dingofs_platform.inventory.models import Cluster, Machine
from dingofs_platform.inventory.ssh_transport import (
    CollectionError,
    SSHConfig,
    execute as execute_ssh,
)


def checked_at():
    return datetime.now(timezone.utc).isoformat()


def machine_probe(machine, settings):
    if not machine.ssh_password_ciphertext:
        return {"state": "unknown", "error": "未配置 SSH 密码", "checked_at": checked_at()}
    try:
        password = decrypt_password(machine.ssh_password_ciphertext, settings.credential_encryption_key)
        result = execute_ssh(
            SSHConfig(machine.address, machine.ssh_port, machine.ssh_user, password),
            {"probe": SAMPLE_COMMAND}, timeout_s=10, max_bytes=65536,
        )["probe"]
        if result.returncode:
            return {"state": "warning", "error": "SSH 命令执行失败", "checked_at": checked_at()}
        try:
            usage = parse_usage(result.stdout)
            usage_error = None
        except ValueError:
            usage = None
            usage_error = "invalid_metrics"
        return {"state": "healthy", "error": None, "usage": usage,
                "usage_error": usage_error, "checked_at": checked_at()}
    except (CollectionError, Problem) as exc:
        return {"state": "warning", "error": exc.code, "checked_at": checked_at()}
    except Exception:
        return {"state": "warning", "error": "worker_failed", "checked_at": checked_at()}


def cluster_probe(cluster, machine, settings):
    if cluster.binding_state != "verified":
        return {"state": "unknown", "error": "管理入口未验证", "checked_at": checked_at()}
    if not machine.ssh_password_ciphertext:
        return {"state": "unknown", "error": "执行机器未配置 SSH 密码", "checked_at": checked_at()}
    try:
        password = decrypt_password(machine.ssh_password_ciphertext, settings.credential_encryption_key)
        output = execute_cluster(
            SSHConfig(machine.address, machine.ssh_port, machine.ssh_user, password),
            ClusterCommand("status", cluster.os_user, cluster.external_name,
                           expected_home=cluster.execution_home),
            timeout_s=min(settings.cluster_status_timeout, 30),
            max_bytes=settings.cluster_max_bytes,
        )
        if output.identity.user != cluster.os_user or (
            cluster.execution_home and output.identity.home != cluster.execution_home
        ):
            raise ClusterExecutionError("invalid_identity")
        if output.returncode:
            raise ClusterExecutionError("query_failed")
        snapshot = parse_cluster_status(output.stdout, cluster.external_name).model_dump()
        return {"state": snapshot["state"], "snapshot": snapshot,
                "error": None, "checked_at": checked_at()}
    except AuthenticationRequired:
        return {"state": "unknown", "error": "needs_password", "checked_at": checked_at()}
    except (CollectionError, ClusterExecutionError, ClusterParseError, Problem) as exc:
        return {"state": "unknown", "error": exc.code,
                "checked_at": checked_at()}
    except Exception:
        return {"state": "unknown", "error": "worker_failed", "checked_at": checked_at()}


class DashboardMonitor:
    def __init__(self, app):
        self.app = app
        self.stop_event = Event()
        self.lock = Lock()
        self.machine_results = {}
        self.cluster_results = {}
        self.thread = None
        self.wake = Event()
        self.running = False
        self.completed = 0
        self.total = 0
        self.last_requested = 0.0
        self.last_error = None

    def start(self):
        self.thread = Thread(target=self._loop, name="dashboard-monitor", daemon=True)
        self.thread.start()

    def stop(self):
        self.stop_event.set()
        self.wake.set()
        if self.thread:
            self.thread.join(timeout=2)

    def snapshot(self):
        with self.lock:
            return (dict(self.machine_results), dict(self.cluster_results),
                    {"running": self.running, "completed": self.completed,
                     "total": self.total, "error": self.last_error})

    def trigger(self):
        with self.lock:
            moment = time.monotonic()
            if self.running or moment - self.last_requested < 30:
                return False
            self.last_requested = moment
            self.wake.set()
            return True

    def _loop(self):
        while not self.stop_event.is_set():
            with self.lock:
                self.running = True
                self.completed = 0
                self.last_error = None
            try:
                self.scan()
            except Exception:
                # A database outage is retried in the next cycle. Never expose
                # exception text, which can contain connection details.
                with self.lock:
                    self.last_error = "后台巡检暂不可用，下一轮将重试"
            finally:
                with self.lock:
                    self.running = False
            self.wake.wait(60)
            self.wake.clear()

    def scan(self):
        with self.app.state.session_factory() as db:
            machines = {m.id: m for m in db.scalars(select(Machine).where(Machine.archived.is_(False)))}
            clusters = list(db.scalars(select(Cluster).where(Cluster.archived.is_(False))))
            db.expunge_all()
        tasks = [("machine", m.id, m, None) for m in machines.values()]
        tasks += [("cluster", c.id, c, machines.get(c.management_machine_id))
                  for c in clusters if c.management_machine_id in machines]
        with self.lock:
            self.total = len(tasks)
            self.completed = 0
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = {
                pool.submit(
                    machine_probe if kind == "machine" else cluster_probe,
                    resource,
                    self.app.state.settings if kind == "machine" else machine,
                    *([] if kind == "machine" else [self.app.state.settings]),
                ): (kind, identifier)
                for kind, identifier, resource, machine in tasks
            }
            for future in as_completed(futures):
                kind, identifier = futures[future]
                try:
                    result = future.result()
                except Exception:
                    result = {"state": "unknown", "error": "worker_failed", "checked_at": checked_at()}
                with self.lock:
                    target = self.machine_results if kind == "machine" else self.cluster_results
                    target[identifier] = result
                    self.completed += 1
        with self.lock:
            self.machine_results = {k: v for k, v in self.machine_results.items() if k in machines}
            ids = {c.id for c in clusters}
            self.cluster_results = {k: v for k, v in self.cluster_results.items() if k in ids}
