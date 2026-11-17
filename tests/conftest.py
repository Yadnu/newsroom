from collections.abc import Iterator

import pytest

from app.archive import MemorySink, set_sink


@pytest.fixture(autouse=True)
def trace_sink() -> Iterator[MemorySink]:
    """Every test gets a fresh in-memory trace sink, so nothing tries to reach Postgres."""
    sink = MemorySink()
    previous = set_sink(sink)
    yield sink
    set_sink(previous)
