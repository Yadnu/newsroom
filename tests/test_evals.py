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
