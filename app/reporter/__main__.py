"""Run one ingest pass: ``uv run python -m app.reporter``."""

import asyncio

from app.archive import start_archive, stop_archive
from app.config import get_settings
from app.log import configure_logging
from app.reporter import ingest_feeds


async def _main() -> None:
    configure_logging(get_settings())
    await start_archive()
    try:
        report = await ingest_feeds()
    finally:
        await stop_archive()
    print(report.model_dump_json(indent=2))


if __name__ == "__main__":
    asyncio.run(_main())
