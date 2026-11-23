import pytest

from evals.latency import STAGES, Stage, markdown, percentile, summarize


def test_percentile_interpolates_like_percentile_cont() -> None:
    xs = [10.0, 20.0, 30.0, 40.0]
    assert percentile(xs, 0.5) == 25.0
    assert percentile(xs, 0.95) == pytest.approx(38.5)
    assert percentile(xs, 0.0) == 10.0 and percentile(xs, 1.0) == 40.0
    assert percentile([7.0], 0.95) == 7.0
    assert percentile([], 0.5) is None


def test_percentile_ignores_input_order_and_rejects_bad_q() -> None:
    assert percentile([30.0, 10.0, 20.0], 0.5) == 20.0
    with pytest.raises(ValueError):
        percentile([1.0], 1.5)


def test_summarize_groups_by_span_and_keeps_every_stage() -> None:
    stages = (Stage("answer", "producer", "answer", "Answer"), Stage("briefing", "x", "y", "Y"))
    rows = [("producer", "answer", 1000.0), ("producer", "answer", 3000.0), ("other", "e", 5.0)]
    stats = summarize(rows, stages)
    assert [(s.stage.event, s.n, s.p50_ms) for s in stats] == [
        ("answer", 2, 2000.0),
        ("y", 0, None),
    ]
    table = markdown(stats)
    assert "| answer | Answer (`producer/answer`) | 2 | 2.0 s | 2.9 s |" in table
    assert "| briefing | Y (`x/y`) | 0 | - | - |" in table


def test_stages_cover_both_paths_with_unique_spans() -> None:
    assert {s.path for s in STAGES} == {"briefing", "answer"}
    keys = [(s.component, s.event) for s in STAGES]
    assert len(set(keys)) == len(keys)
