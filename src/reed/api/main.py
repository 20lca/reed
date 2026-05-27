from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI

from reed.api.routes import router
from reed.brightway_api import ensure_brightway_databases
from reed.jobs.service import CalculationService
from reed.pipeline.service import ReedCalculationPipeline
from reed.storage.files import FileStorage
from reed.utils import Config


def create_app(
    *,
    settings: Config | None = None,
    storage: FileStorage | None = None,
    pipeline: ReedCalculationPipeline | None = None,
) -> FastAPI:
    settings = settings or Config()
    storage = storage or FileStorage(settings.STORAGE_ROOT)
    bootstrap_brightway = pipeline is None
    pipeline = pipeline or ReedCalculationPipeline(settings)

    service = CalculationService(
        storage=storage,
        pipeline=pipeline,
        settings=settings,
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.calculation_service = service
        if settings.IMPORT_BRIGHTWAY_ON_STARTUP and bootstrap_brightway:
            ensure_brightway_databases(settings)
        service.start_worker()
        try:
            yield
        finally:
            service.stop_worker()

    app = FastAPI(title="REED REST v1", version="0.1.0", lifespan=lifespan)
    app.include_router(router)
    return app


app = create_app()
