"""FastAPI entry point: ``uv run fastapi dev app/main.py``."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from importlib.metadata import version
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from app.anchor.routes import router as anchor_router
from app.archive import start_archive, stop_archive
from app.archive.routes import router as archive_router
from app.config import get_settings
from app.log import configure_logging, get_logger
from app.press.routes import router as press_router


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
app.include_router(anchor_router)
app.include_router(press_router)
# Telecast audio (task 8.3): WAV files under media_dir, with HTTP Range for seeking.
app.mount(
    "/media", StaticFiles(directory=Path(get_settings().media_dir), check_dir=False), name="media"
)


@app.get("/health")
async def health() -> Health:
    """Liveness only. Does not touch Postgres or Redis."""
    return Health(status="ok", version=version("newsroom"), env=get_settings().env)
