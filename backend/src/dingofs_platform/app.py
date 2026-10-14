from .performance.routes import router as performance
from .performance.manager import PerformanceManager
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
from .inventory.overview import router as overview
from .inventory.routes import router as inventory
from .clusters.routes import router as clusters
from .resources.routes import router as resources
from .mount_profiles.routes import router as mount_profiles
from .cache_profiles.routes import router as cache_profiles
from .storage.routes import router as storage


def create_app(settings=None):
    settings = settings or Settings()

    @asynccontextmanager
    async def lifespan(app):
        app.state.remote_manager.startup()
        if settings.performance_worker_enabled:
            app.state.performance_manager.start()
        if settings.dashboard_monitor_enabled:
            app.state.dashboard_monitor.start()
        try:
            yield
        finally:
            if settings.dashboard_monitor_enabled:
                app.state.dashboard_monitor.stop()
            app.state.performance_manager.stop()
            app.state.remote_manager.shutdown()

    app = FastAPI(title="DingoFS Test Platform", version="0.1.0", lifespan=lifespan)
    app.state.remote_manager = RemoteManager(app)
    app.state.performance_manager = PerformanceManager(app)
    app.state.dashboard_monitor = DashboardMonitor(app)
    app.state.settings = settings
    app.state.engine = create_engine(
        settings.database_url, pool_pre_ping=True, connect_args={"connect_timeout": 3}
    )
    app.state.session_factory = sessionmaker(app.state.engine, expire_on_commit=False)

    @app.middleware("http")
    async def request_identity(request, call_next):
        request.state.request_id = str(uuid4())
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
            return {"status": "ok"}
        except SQLAlchemyError:
            return JSONResponse(status_code=503, content={"status": "unavailable"})

    app.include_router(auth)
    app.include_router(configs)
    app.include_router(users)
    app.include_router(hardware)
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
    app.include_router(inventory)
    return app
