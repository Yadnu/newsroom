"""Red team set (task 6.1): the set loads and the deterministic layers pass the offline gate."""

from collections import Counter
from pathlib import Path

import pytest

from evals.redteam import (
    CLEAR_KINDS,
    JUDGE_KINDS,
    SCREEN_KINDS,
    ClearCase,
    ClearClaim,
    Outcome,
    load,
    offline_failures,
    run_clear,
    run_offline,
    score,
)

DATA = Path(__file__).resolve().parents[1] / "evals/data/redteam_v1.json"


def test_set_covers_satire_stale_and_injection_in_every_suite() -> None:
    s = load(DATA)
    assert set(Counter(c.kind for c in s.judge)) == set(JUDGE_KINDS)
    assert set(Counter(c.kind for c in s.screen)) == set(SCREEN_KINDS)
    assert set(Counter(c.kind for c in s.clear)) == set(CLEAR_KINDS)
    assert len(s.judge) >= 20 and len(s.screen) >= 40 and len(s.clear) >= 30
    assert sum(c.expect == "approve" for c in s.judge) >= 4  # controls, not only attacks
    assert sum(c.layer == "rules" for c in s.screen) >= 15


def test_offline_gate_passes() -> None:
    """The CI gate: Standards Desk rules and screen rules get every gated case right."""
    failures = offline_failures(run_offline(load(DATA)))
    assert failures == [], [f"{o.id}: {o.detail}" for o in failures]


def test_clear_case_uses_the_stored_state() -> None:
    ok = ClearCase("x", "control", "clear", "Acme shipped Nova.", (ClearClaim(),))
    assert run_clear(ok).hit is False
    retracted = ClearCase(
        "y", "stale", "block", "Acme shipped Nova.", (ClearClaim(live_evidence=0),)
    )
    assert "retracted" in run_clear(retracted).detail
    unstored = ClearCase(
        "z", "unverified", "block", "Acme shipped Nova.", (ClearClaim(stored=False),)
    )
    assert "not stored" in run_clear(unstored).detail


def test_known_gaps_are_reported_not_gated() -> None:
    gap = ClearCase(
        "g",
        "opinion",
        "block",
        "Acme said it shipped Nova, a shocking move.",
        (ClearClaim(),),
        known_gap="attribution exempts the sentence",
    )
    o = run_clear(gap)
    assert o.correct is False and not o.gated and offline_failures([o]) == []


def test_score_per_suite() -> None:
    outs = [
        Outcome("a", "judge", "satire", "flag", True),
        Outcome("b", "judge", "satire", "flag", False),
        Outcome("c", "judge", "stale", "approve", True),
        Outcome("d", "judge", "stale", "approve", False),
        Outcome("e", "judge", "stale", "flag", None),
        Outcome("f", "screen", "benign", "allow", False),
    ]
    s = score(outs)
    assert s["judge"]["catch_rate"] == 0.5 and s["judge"]["false_hit_rate"] == 0.5
    assert s["judge"]["errors"] == 1 and s["judge"]["misses"] == ["b", "c"]
    assert s["judge"]["by_kind"]["satire"] == {"n": 2, "correct": 1}
    assert s["screen"]["catch_rate"] is None and s["screen"]["false_hit_rate"] == 0.0


def test_load_rejects_bad_cases(tmp_path: Path) -> None:
    bad = tmp_path / "bad.json"
    bad.write_text(
        '{"version": "v", "today": "2026-11-20", "judge": [], "clear": [], "screen": ['
        '{"id": "a", "kind": "benign", "expect": "block", "transcript": "hi there"}]}'
    )
    with pytest.raises(ValueError, match="benign"):
        load(bad)
