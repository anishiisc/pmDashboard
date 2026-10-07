from __future__ import annotations

import pytest

from app.pipeline.rollup import compute_overall_rating, run_rollup
from app.schemas import Quote, Verdict, VerdictOutput


def _make_verdicts(**overrides) -> VerdictOutput:
    """
    Build a VerdictOutput. Defaults all items to Good/10.
    Pass overrides as item_id={"final_rating": ..., "verification_score": ...}
    """
    all_ids = ["P1.1", "P1.2", "P1.3", "P2.1", "P2.2", "P2.3", "P3.1", "P3.2", "P3.3"]
    verdicts = []
    for item_id in all_ids:
        ov = overrides.get(item_id, {})
        verdicts.append(
            Verdict(
                item_id=item_id,
                draft_rating=ov.get("draft_rating", "Good"),
                final_rating=ov.get("final_rating", "Good"),
                verification_score=ov.get("verification_score", 10),
                verdict=ov.get("verdict", "upheld"),
                evidence=[Quote(ref="D1:L001", text="Evidence text.")],
                reasoning="Test reasoning.",
            )
        )
    return VerdictOutput(verdicts=verdicts)


def test_worst_of_poor_dominates():
    vo = _make_verdicts(**{"P1.1": {"final_rating": "Poor", "verification_score": 8}})
    pillars = run_rollup(vo)
    p1 = next(p for p in pillars if p["pillar_id"] == "P1")
    assert p1["rating"] == "Poor"


def test_worst_of_medium_no_poor():
    vo = _make_verdicts(
        **{
            "P1.1": {"final_rating": "Good", "verification_score": 9},
            "P1.2": {"final_rating": "Medium", "verification_score": 7},
            "P1.3": {"final_rating": "Good", "verification_score": 8},
        }
    )
    pillars = run_rollup(vo)
    p1 = next(p for p in pillars if p["pillar_id"] == "P1")
    assert p1["rating"] == "Medium"


def test_all_good():
    vo = _make_verdicts()
    pillars = run_rollup(vo)
    for p in pillars:
        assert p["rating"] == "Good"


def test_all_not_evidenced():
    vo = _make_verdicts(
        **{iid: {"final_rating": "Not Evidenced", "verification_score": 5} for iid in
           ["P1.1", "P1.2", "P1.3"]}
    )
    pillars = run_rollup(vo)
    p1 = next(p for p in pillars if p["pillar_id"] == "P1")
    assert p1["rating"] == "Not Evidenced"


def test_coverage_gap_when_one_not_evidenced():
    vo = _make_verdicts(
        **{"P2.1": {"final_rating": "Not Evidenced", "verification_score": 7}}
    )
    pillars = run_rollup(vo)
    p2 = next(p for p in pillars if p["pillar_id"] == "P2")
    assert p2["coverage_gap"] is True


def test_no_coverage_gap_all_evidenced():
    vo = _make_verdicts()
    pillars = run_rollup(vo)
    for p in pillars:
        assert p["coverage_gap"] is False


def test_review_threshold_propagation():
    vo = _make_verdicts(**{"P3.2": {"final_rating": "Poor", "verification_score": 4}})
    pillars = run_rollup(vo)
    p3 = next(p for p in pillars if p["pillar_id"] == "P3")
    assert p3["manager_review_required"] is True
    item = next(i for i in p3["items"] if i["item_id"] == "P3.2")
    assert item["manager_review_required"] is True


def test_review_not_required_when_all_above_threshold():
    vo = _make_verdicts()
    pillars = run_rollup(vo)
    for p in pillars:
        assert p["manager_review_required"] is False


def test_overall_rating_worst_pillar():
    vo = _make_verdicts(**{"P3.1": {"final_rating": "Poor", "verification_score": 8}})
    pillars = run_rollup(vo)
    overall = compute_overall_rating(pillars)
    assert overall == "Poor"


def test_confidence_mean_and_min():
    vo = _make_verdicts(
        **{
            "P1.1": {"verification_score": 8},
            "P1.2": {"verification_score": 6},
            "P1.3": {"verification_score": 4},
        }
    )
    pillars = run_rollup(vo)
    p1 = next(p for p in pillars if p["pillar_id"] == "P1")
    assert p1["confidence_mean"] == 6.0
    assert p1["confidence_min"] == 4
