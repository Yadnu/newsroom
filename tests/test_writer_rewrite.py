from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest

import app.shared.llm as llm
import app.writer.rewrite as rewrite
from app.config import Settings
from app.writer import ClaimFeedback, DraftClaim, DraftLine, WriterError, rewrite_line
from app.writer.draft import CleanLine, SourceText
from app.writer.prompts import load_prompt
from tests.test_writer_draft import WHEN, FakeGroq, line, seg

S1 = SourceText(uuid4(), "Ars", "Acme ships", "Acme said it began shipping the Nova chip.", WHEN)
S2 = SourceText(uuid4(), "Verge", "Nova ships", "Acme says Nova doubles throughput.", WHEN)


@pytest.fixture
def groq() -> Any:
    def install(*contents: str) -> FakeGroq:
        fake = FakeGroq(*contents)
        settings = Settings(_env_file=None, groq_api_key="gsk-test")  # type: ignore[call-arg]
        llm.set_gateway(llm.Gateway(settings, transport=httpx.MockTransport(fake)))
        return fake

    yield install
    llm.set_gateway(None)


@pytest.fixture
def db(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    state: dict[str, Any] = {"sources": [S1, S2], "stored": None}

    async def fake_load(story_id: UUID) -> tuple[str, list[SourceText]]:
        return "Acme ships Nova", state["sources"]

    async def fake_store(old: DraftLine, clean: CleanLine, round_no: int) -> DraftLine:
        state["stored"] = (old, clean, round_no)
        return DraftLine(
            id=old.id,
            story_id=old.story_id,
            order=old.order,
            text=clean.text,
            claims=[
                DraftClaim(id=uuid4(), text=c.text, source_ids=c.source_ids) for c in clean.claims
            ],
        )

    monkeypatch.setattr(rewrite, "load_story_sources", fake_load)
    monkeypatch.setattr(rewrite, "_store_rewrite", fake_store)
    return state


OLD = DraftLine(
    id=uuid4(),
    story_id=uuid4(),
    order=3,
    text="Acme began shipping the Nova chip.",
    claims=[DraftClaim(id=uuid4(), text="Acme began shipping Nova.", source_ids=[S1.id])],
)
FEEDBACK = [
    ClaimFeedback(
        text="Acme began shipping Nova.",
        verdict="rewrite",
        reason="attributed: the evidence presents this as <Acme's> statement",
    )
]
GOOD = seg(
    line(
        "Acme says it has begun shipping the Nova chip.",
        ("Acme says it began shipping Nova.", ["S1"]),
    )
)


async def test_rewrite_prompt_has_line_feedback_and_escaped_sources(
    groq: Any,
    db: dict[str, Any],
) -> None:
    fake = groq(GOOD)
    new = await rewrite_line(OLD, FEEDBACK, 1)

    (body,) = fake.bodies
    system, user = body["messages"]
    assert body["model"] == "openai/gpt-oss-20b"  # task "draft"
    assert system == {"role": "system", "content": load_prompt("writer/draft_system")}
    content = user["content"]
    assert "<line>Acme began shipping the Nova chip.</line>" in content
    assert "- [rewrite] Acme began shipping Nova.: attributed:" in content
    assert "&lt;Acme's&gt;" in content  # Editor reason is escaped too
    assert '<source id="S1" outlet="Ars"' in content and '<source id="S2"' in content
    assert "Story: Acme ships Nova" in content

    stored_old, clean, round_no = db["stored"]
    assert stored_old is OLD and round_no == 1
    assert clean.claims[0].source_ids == [S1.id]
    assert new.id == OLD.id and new.order == 3
    assert new.text == "Acme says it has begun shipping the Nova chip."


async def test_more_than_one_line_is_resampled(groq: Any, db: dict[str, Any]) -> None:
    two = seg(
        line("Acme says it ships Nova.", ("Acme says it ships Nova.", ["S1"])),
        line("Acme says Nova is fast.", ("Acme says Nova is fast.", ["S2"])),
    )
    fake = groq(two, GOOD)
    await rewrite_line(OLD, FEEDBACK, 2)
    assert len(fake.bodies) == 2
    assert "exactly one line, not 2" in fake.bodies[1]["messages"][3]["content"]
    assert db["stored"][2] == 2


async def test_invalid_twice_raises_and_stores_nothing(
    groq: Any,
    db: dict[str, Any],
) -> None:
    bad = seg(line("Acme ships Nova.", ("Acme ships Nova.", ["S9"])))
    groq(bad, bad)
    with pytest.raises(WriterError, match="no known source"):
        await rewrite_line(OLD, FEEDBACK, 1)
    assert db["stored"] is None


async def test_story_without_sources_raises(groq: Any, db: dict[str, Any]) -> None:
    db["sources"] = []
    fake = groq()
    with pytest.raises(WriterError, match="no usable sources"):
        await rewrite_line(OLD, FEEDBACK, 1)
    assert fake.bodies == []
