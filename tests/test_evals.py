from collections import Counter
from pathlib import Path

import pytest

from evals.scoring import EvalCase, load, score

DATA = Path(__file__).resolve().parents[1] / "evals/data/judge_v1.json"


def test_eval_set_has_100_labelled_claims_and_30_planted_falsehoods() -> None:
    s = load(DATA)
    kinds = Counter(c.kind for c in s.cases)
    assert kinds["planted"] == 30
    assert len(s.cases) - kinds["planted"] == 100
    labelled = Counter(c.expect for c in s.cases if c.kind != "planted")
    assert labelled["approve"] >= 50 and labelled["flag"] >= 30
    assert {"unattributed", "distorted", "unsupported", "stale", "sensitive_single"} <= set(kinds)
    assert all(len({p.outlet for p in c.passages}) >= 2 for c in s.cases)
    assert str(s.today) == "2026-11-18"


def _case(i: int, expect: str, kind: str) -> EvalCase:
    return EvalCase(f"c{i}", "s", "text", expect, kind, ())  # type: ignore[arg-type]


def test_score_metrics() -> None:
    cases = [
        _case(1, "flag", "planted"),
        _case(2, "flag", "planted"),
        _case(3, "flag", "unattributed"),
        _case(4, "approve", "supported"),
        _case(5, "approve", "supported"),
        _case(6, "approve", "supported"),
    ]
    verdicts = {
        "c1": "rejected",  # caught
        "c2": "approved",  # missed
        "c3": "rewrite",  # caught
        "c4": "approved",
        "c5": "rewrite",  # false flag
        "c6": "pending",  # judge failed: excluded
    }
    out = score(cases, verdicts)
    assert out["judged"] == 5 and out["errors"] == 1
    assert out["catch_rate"] == 0.5
    assert out["recall"] == pytest.approx(2 / 3, abs=1e-4)
    assert out["precision"] == pytest.approx(2 / 3, abs=1e-4)
    assert out["false_flag_rate"] == 0.5
    assert out["missed_planted"] == ["c2"] and out["false_flags"] == ["c5"]
    assert out["by_kind"]["planted"] == {"n": 2, "correct": 1, "accuracy": 0.5}


def test_score_with_nothing_judged() -> None:
    out = score([_case(1, "flag", "planted")], {})
    assert out["catch_rate"] is None and out["judged"] == 0


CONTRA = Path(__file__).resolve().parents[1] / "evals/data/contradictions_v1.json"


def test_contradiction_set_and_score() -> None:
    s = load(CONTRA)
    kinds = Counter(c.kind for c in s.cases)
    assert (
        kinds["contradicted"] >= 10
        and kinds["conflict_attributed"] >= 5
        and kinds["supported"] >= 8
    )
    assert all(len({p.outlet for p in c.passages}) >= 2 for c in s.cases)
    cases = [
        _case(1, "flag", "contradicted"),
        _case(2, "flag", "contradicted"),
        _case(3, "approve", "conflict_attributed"),
    ]
    out = score(cases, {"c1": "rewrite", "c2": "approved", "c3": "approved"})
    assert out["contradiction_catch"] == 0.5 and out["false_flag_rate"] == 0.0
    assert out["by_kind"]["conflict_attributed"] == {"n": 1, "correct": 1, "accuracy": 1.0}


def test_answered_by_reads_the_model_off_the_judge_span() -> None:
    import uuid

    from app.archive import MemorySink, set_sink, span
    from evals.run_evals import answered_by

    sink = MemorySink()
    previous = set_sink(sink)
    try:
        mine, other = uuid.uuid4(), uuid.uuid4()
        for cid, model in (
            (other, "openai/gpt-oss-120b"),
            (mine, "openrouter:openai/gpt-oss-120b"),
        ):
            with (
                span("editor", "judge_claim", claim_id=cid),
                span("llm-gateway", "complete.judge") as s,
            ):
                s.set(model=model)
        assert answered_by(sink.traces, mine) == "openrouter:openai/gpt-oss-120b"
        assert answered_by(sink.traces, uuid.uuid4()) is None
    finally:
        set_sink(previous)


def test_models_used_counts_the_latest_judged_row_per_case() -> None:
    import json

    from evals.run_evals import models_used

    rows = [
        {"id": "a", "verdict": "pending", "model": "openai/gpt-oss-120b"},
        {"id": "a", "verdict": "approved", "model": "openrouter:openai/gpt-oss-120b"},
        {"id": "b", "verdict": "rewrite", "model": "openai/gpt-oss-120b"},
        {"id": "c", "verdict": "pending", "model": "openai/gpt-oss-120b"},
    ]
    assert models_used(json.dumps(r) for r in rows) == {
        "openrouter:openai/gpt-oss-120b": 1,
        "openai/gpt-oss-120b": 1,
    }
