import os
from collections.abc import Iterator

import pytest
from sqlalchemy.engine import make_url

from app.archive import MemorySink, set_sink
from app.config import Settings


def same_database(a: str, b: str) -> bool:
    """True if two SQLAlchemy URLs point at the same host, port and database."""
    ua, ub = make_url(a), make_url(b)
    return (ua.host, ua.port or 5432, ua.database) == (ub.host, ub.port or 5432, ub.database)


def pytest_configure(config: pytest.Config) -> None:
    """Integration fixtures TRUNCATE tables, so never let them run against the app's database."""
    test_url = os.environ.get("NEWSROOM_TEST_DATABASE_URL")
    if test_url and same_database(test_url, Settings().database_url):
        pytest.exit(
            "NEWSROOM_TEST_DATABASE_URL points at NEWSROOM_DATABASE_URL; integration tests would"
            " truncate it. Use a separate database.",
            returncode=2,
        )


@pytest.fixture(autouse=True)
def trace_sink() -> Iterator[MemorySink]:
    """Every test gets a fresh in-memory trace sink, so nothing tries to reach Postgres."""
    sink = MemorySink()
    previous = set_sink(sink)
    yield sink
    set_sink(previous)
