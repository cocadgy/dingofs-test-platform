from .performance.routes import router as performance
from .performance.manager import PerformanceManager
from .functional.routes import router as functional
from .functional.drafts import router as functional_drafts
from .functional.environments.routes import router as functional_environments
from .functional.environments.service import sync_predefined
from .functional.manager import FunctionalManager
from .tool_packages.source import router as tool_source
from .tool_packages.routes import router as tool_packages
from dingofs_platform.clusters import models as cluster_models  # noqa: F401
from uuid import uuid4
from fastapi import FastAPI
from contextlib import asynccontextmanager
from .dashboard.monitor import DashboardMonitor
from .dashboard.routes import router as dashboard
from .remote.manager import RemoteManager
from .remote.routes import router as remote
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from .settings import Settings
from .errors import Problem
from .auth.routes import router as auth
from .auth.users import router as users
from .configuration.routes import router as configs
from .inventory.hardware_routes import router as hardware
from .inventory.guided_routes import router as guided_start
from .inventory.overview import router as overview
from .inventory.routes import router as inventory
from .clusters.routes import router as clusters
from .resources.routes import router as resources
from .mount_profiles.routes import router as mount_profiles
from .cache_profiles.routes import router as cache_profiles
from .storage.routes import router as storage
from time import monotonic
from threading import Lock
import logging
from starlette.concurrency import run_in_threadpool


def _check_guided_migration(connection):
    revisions = set(connection.scalars(text('SELECT version_num FROM alembic_version')))
    if revisions != {'7b1c9e4a602d'}:
        raise ValueError('guided migration is unavailable')


def create_app(settings=None):
    settings = settings or Settings()

    @asynccontextmanager
    async def lifespan(app):
        preset_root=settings.functional_source_root.parent/'conf/env'
        if preset_root.is_dir():
            try:
                with app.state.session_factory.begin() as db:
                    sync_predefined(db,preset_root)
            except (OSError, ValueError):
                # Optional source refresh must not remove history/worker access.
                # Enabled readiness still rejects an unavailable source ABI.
                logging.getLogger(__name__).warning('Functional source refresh unavailable')
        app.state.remote_manager.startup()
        if settings.performance_worker_enabled:
            app.state.performance_manager.start()
        if settings.performance_worker_enabled or settings.functional_worker_enabled:
            app.state.functional_manager.start()
        if settings.dashboard_monitor_enabled:
            app.state.dashboard_monitor.start()
        try:
            yield
        finally:
            if settings.dashboard_monitor_enabled:
                app.state.dashboard_monitor.stop()
            app.state.performance_manager.stop()
            app.state.functional_manager.stop()
            app.state.remote_manager.shutdown()

    app = FastAPI(title="DingoFS Test Platform", version="0.1.0", lifespan=lifespan)
    app.state.remote_manager = RemoteManager(app)
    app.state.performance_manager = PerformanceManager(app)
    app.state.functional_manager = FunctionalManager(app)
    app.state.dashboard_monitor = DashboardMonitor(app)
    app.state.settings = settings
    app.state.engine = create_engine(
        settings.database_url, pool_pre_ping=True, connect_args={"connect_timeout": 3}
    )
    app.state.session_factory = sessionmaker(app.state.engine, expire_on_commit=False)
    source_check = {'key': None, 'expires': 0.0}
    source_check_lock = Lock()

    def check_guided_readiness():
        """Check installed schema and pure source ABI without remote probes.

        Source imports are bounded and cached for 30 seconds. Preflight still
        independently rehashes its exact source. Schema checks are uncached.
        """
        from sqlalchemy import select
        from .functional.models import (FunctionalRun, FunctionalModuleRun,
            FunctionalPreflight, FunctionalEvent, FunctionalResource)
        from .operations.models import OperationLease
        from .functional.drafts import Draft
        from .functional.source_bridge import inspect_source
        with app.state.engine.connect() as connection:
            for model in (FunctionalRun, FunctionalModuleRun, FunctionalPreflight,
                          FunctionalEvent, FunctionalResource, Draft, OperationLease):
                connection.execute(select(model).limit(0))
            _check_guided_migration(connection)
        root = settings.functional_source_root.parent
        entry = root / 'src/test_runner/functional_contracts.py'
        key = (str(root), entry.stat().st_mtime_ns, entry.stat().st_size)
        if not settings.functional_source_root.is_dir() or not (root / 'conf/env').is_dir():
            raise ValueError('guided source is unavailable')
        with source_check_lock:
            if source_check['key'] == key and source_check['expires'] > monotonic():
                return
            # Missing environment exercises imports and wire schema without
            # falsely advertising any module/environment as supported.
            inspect_source(root, '__platform_readiness__', {})
            source_check.update(key=key, expires=monotonic() + 30)

    def require_guided_readiness():
        try:
            check_guided_readiness()
        except (SQLAlchemyError, OSError, ValueError) as exc:
            raise Problem(503, 'guided_runtime_unavailable',
                          '引导功能测试迁移或源契约不可用') from exc

    app.state.require_guided_readiness = require_guided_readiness

    @app.middleware("http")
    async def request_identity(request, call_next):
        request.state.request_id = str(uuid4())
        path = request.url.path
        guarded = path in ('/api/v1/functional/guided/metadata',
                           '/api/v1/functional/guided/compatibility',
                           '/api/v1/functional/preflight')
        if request.method == 'POST' and path == '/api/v1/functional/runs':
            try:
                guarded = (await request.json()).get('version') == 2
            except (ValueError, AttributeError):
                pass
        if (request.method == 'POST' and path.startswith('/api/v1/functional/runs/')
                and path.endswith('/rerun')):
            try:
                guarded = 'idempotency_key' in (await request.json())
            except (ValueError, TypeError):
                pass
        if settings.functional_guided_enabled and guarded:
            try:
                # Preserve authentication/CSRF precedence over capability checks.
                from .auth.dependencies import current_user
                await run_in_threadpool(current_user, request)
                await run_in_threadpool(require_guided_readiness)
            except Problem as exc:
                return JSONResponse(status_code=exc.status, content={
                    'code': exc.code, 'message': exc.message, 'details': exc.details},
                    headers={'X-Request-ID': request.state.request_id})
        response = await call_next(request)
        response.headers["X-Request-ID"] = request.state.request_id
        return response

    @app.exception_handler(Problem)
    async def problem(request, exc):
        return JSONResponse(
            status_code=exc.status,
            content={"code": exc.code, "message": exc.message, "details": exc.details},
        )

    @app.exception_handler(RequestValidationError)
    async def invalid(request, exc):
        if request.url.path.startswith('/api/v1/performance/'):
            messages=['.'.join(str(v) for v in e['loc'][1:])+': '+e['msg'] for e in exc.errors()]
            return JSONResponse(status_code=422,content={'code':'invalid_request','message':'；'.join(messages),'details':{}})
        return JSONResponse(
            status_code=422,
            content={
                "code": "invalid_request",
                "message": "请求字段格式错误",
                "details": {},
            },
        )

    @app.exception_handler(IntegrityError)
    async def conflict(request, exc):
        return JSONResponse(
            status_code=409,
            content={
                "code": "conflict",
                "details": {},
                "message": "资源名称、地址或标识已存在，或关联资源已改变",
            },
        )

    @app.get("/health/live")
    def live():
        return {"status": "ok"}

    @app.get("/health/ready")
    def ready():
        try:
            with app.state.engine.connect() as db:
                db.execute(text("SELECT 1"))
            if settings.functional_guided_enabled:
                check_guided_readiness()
                return {"status": "ok", "guided_functional": "ready"}
            return {"status": "ok"}
        except (SQLAlchemyError, OSError, ValueError):
            return JSONResponse(status_code=503, content={"status": "unavailable"})

    app.include_router(auth)
    app.include_router(configs)
    app.include_router(users)
    app.include_router(hardware)
    app.include_router(guided_start)
    app.include_router(overview)
    app.include_router(dashboard)
    app.include_router(clusters)
    app.include_router(resources)
    app.include_router(remote)
    app.include_router(storage)
    app.include_router(cache_profiles)
    app.include_router(mount_profiles)
    app.include_router(tool_source)
    app.include_router(tool_packages)
    app.include_router(performance)
    app.include_router(functional_environments)
    app.include_router(functional)
    app.include_router(functional_drafts)
    app.include_router(inventory)
    return app
