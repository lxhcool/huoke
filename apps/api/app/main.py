from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes.feedback import router as feedback_router
from app.api.routes.health import router as health_router
from app.api.routes.imports import router as imports_router
from app.api.routes.jobs import router as jobs_router
from app.api.routes.prompt_profiles import router as prompt_profiles_router
from app.api.routes.search import router as search_router
from app.api.routes.source_auth import router as source_auth_router
from app.core.config import settings
from app.db.base import Base
from app.db.session import engine


def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.app_name,
        version="0.1.0",
        description="AI 获客线索发现 Agent API",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.allowed_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(health_router, prefix="/api")
    app.include_router(jobs_router, prefix="/api")
    app.include_router(imports_router, prefix="/api")
    app.include_router(feedback_router, prefix="/api")
    app.include_router(prompt_profiles_router, prefix="/api")
    app.include_router(search_router, prefix="/api")
    app.include_router(source_auth_router, prefix="/api")

    @app.on_event("startup")
    def startup() -> None:
        Base.metadata.create_all(bind=engine)

    return app


app = create_app()
