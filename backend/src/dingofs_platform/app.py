from uuid import uuid4
from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from .settings import Settings
from .errors import Problem
from .auth.routes import router as auth
from .configuration.routes import router as configs
from .inventory.routes import router as inventory


def create_app(settings=None):
    settings = settings or Settings()
    app = FastAPI(title="DingoFS Test Platform", version="0.1.0")
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
    app.include_router(inventory)
    return app
