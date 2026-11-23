"""Contract test for the data-model node. No database needed."""

from sqlalchemy import ForeignKey
from sqlmodel import SQLModel

import app.db as db

TABLES = {
    "sources",
    "telecasts",
    "stories",
    "story_sources",
    "briefings",
    "script_lines",
    "claims",
    "claim_evidence",
    "claim_sources",
    "corrections",
    "traces",
}


def _fk(table: str, column: str) -> ForeignKey:
    (fk,) = SQLModel.metadata.tables[table].c[column].foreign_keys
    return fk


def test_all_contract_tables_exist() -> None:
    assert set(SQLModel.metadata.tables) == TABLES


def test_trace_chain_foreign_keys() -> None:
    assert _fk("story_sources", "source_id").column.table.name == "sources"
    assert _fk("story_sources", "story_id").column.table.name == "stories"
    assert _fk("script_lines", "story_id").column.table.name == "stories"
    assert _fk("claims", "script_line_id").column.table.name == "script_lines"
    assert _fk("claim_evidence", "claim_id").column.table.name == "claims"
    assert _fk("claim_evidence", "source_id").column.table.name == "sources"
    assert _fk("claim_sources", "claim_id").column.table.name == "claims"
    assert _fk("claim_sources", "source_id").column.table.name == "sources"
    assert _fk("corrections", "source_id").column.table.name == "sources"
    assert _fk("corrections", "script_line_id").column.table.name == "script_lines"


def test_delete_rules_keep_the_chain_intact() -> None:
    assert _fk("script_lines", "briefing_id").ondelete == "CASCADE"
    assert _fk("claims", "script_line_id").ondelete == "CASCADE"
    assert _fk("claim_sources", "claim_id").ondelete == "CASCADE"
    assert _fk("claim_sources", "source_id").ondelete == "RESTRICT"
    assert _fk("claim_evidence", "claim_id").ondelete == "CASCADE"
    assert _fk("claim_evidence", "source_id").ondelete == "RESTRICT"
    assert _fk("script_lines", "story_id").ondelete == "SET NULL"
    assert _fk("traces", "briefing_id").ondelete == "SET NULL"


def test_embedding_columns_use_decided_dimension() -> None:
    assert db.EMBEDDING_DIM == 1024
    for table, col in (("sources", "embedding"), ("stories", "centroid")):
        assert SQLModel.metadata.tables[table].c[col].type.dim == db.EMBEDDING_DIM


def test_hnsw_cosine_indexes() -> None:
    for table, col in (("sources", "embedding"), ("stories", "centroid")):
        indexes = {i.name: i for i in SQLModel.metadata.tables[table].indexes}
        idx = indexes[f"ix_{table}_{col}_hnsw"]
        assert idx.dialect_options["postgresql"]["using"] == "hnsw"
        assert idx.dialect_options["postgresql"]["ops"] == {col: "vector_cosine_ops"}


def test_dedupe_keys_are_unique() -> None:
    src = SQLModel.metadata.tables["sources"]
    assert src.c.url.unique
    assert src.c.content_hash.unique


def test_verdict_defaults_to_pending_and_is_plain_text() -> None:
    claim = db.Claim(script_line_id=db.Briefing(target_minutes=3).id, text="x")
    assert claim.verdict is db.Verdict.pending
    assert str(SQLModel.metadata.tables["claims"].c.verdict.type) == "VARCHAR(20)"
