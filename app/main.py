"""FastAPI entry point: ``uv run fastapi dev app/main.py``."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from importlib.metadata import version

from fastapi import FastAPI
from pydantic import BaseModel

from app.archive import start_archive, stop_archive
from app.archive.routes import router as archive_router
from app.config import get_settings
from app.log import configure_logging, get_logger


class Health(BaseModel):
    status: str
    version: str
    env: str


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    configure_logging(settings)
    get_logger(__name__).info("startup", component="api", env=settings.env)
    await start_archive()
    try:
        yield
    finally:
        await stop_archive()


app = FastAPI(title="Newsroom", lifespan=lifespan)
app.include_router(archive_router)


@app.get("/health")
async def health() -> Health:
    """Liveness only. Does not touch Postgres or Redis."""
    return Health(status="ok", version=version("newsroom"), env=get_settings().env)
