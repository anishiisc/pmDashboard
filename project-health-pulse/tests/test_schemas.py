from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.schemas import (
    ExtractionOutput,
    ExtractedItem,
    PillarRecommendation,
    Quote,
    Recommendation,
    VerdictOutput,
    Verdict,
)


def _make_item(item_id: str, rating: str = "Good", evidence=None) -> dict:
    if evidence is None and rating != "Not Evidenced":
        evidence = [{"ref": "D1:L001", "text": "Some evidence text here."}]
    elif evidence is None:
        evidence = []
    return {
        "item_id": item_id,
        "rating": rating,
        "evidence": evidence,
        "rationale": "Test rationale.",
    }


ALL_IDS = ["P1.1", "P1.2", "P1.3", "P2.1", "P2.2", "P2.3", "P3.1", "P3.2", "P3.3"]


def _full_extraction(**overrides) -> ExtractionOutput:
    items = [_make_item(iid, **overrides.get(iid, {})) for iid in ALL_IDS]
    return ExtractionOutput(items=items)


def test_valid_extraction():
    e = _full_extraction()
    assert len(e.items) == 9


def test_duplicate_item_id_rejected():
    items = [_make_item("P1.1")] * 9
    with pytest.raises(ValidationError, match="exactly one of each ID"):
        ExtractionOutput(items=items)


def test_missing_item_id_rejected():
    items = [_make_item(iid) for iid in ALL_IDS[:-1]] + [_make_item("P1.1")]
    with pytest.raises(ValidationError):
        ExtractionOutput(items=items)


def test_evidence_required_for_non_not_evidenced():
    with pytest.raises(ValidationError, match="evidence must be non-empty"):
        ExtractedItem(
            item_id="P1.1",
            rating="Good",
            evidence=[],
            rationale="No evidence given but should be required.",
        )


def test_not_evidenced_allows_empty_evidence():
    item = ExtractedItem(
        item_id="P1.1",
        rating="Not Evidenced",
        evidence=[],
        rationale="No signal in transcripts.",
    )
    assert item.evidence == []


def test_invalid_line_ref():
    with pytest.raises(ValidationError, match="Invalid line reference"):
        Quote(ref="BAD_REF", text="Some text.")


def test_valid_line_ref():
    q = Quote(ref="D3:L014", text="Some text.")
    assert q.ref == "D3:L014"


def test_verification_score_bounds():
    def make_verdict(score: int) -> dict:
        return {
            "item_id": "P1.1",
            "draft_rating": "Good",
            "final_rating": "Good",
            "verification_score": score,
            "verdict": "upheld",
            "evidence": [{"ref": "D1:L001", "text": "Evidence."}],
            "reasoning": "Test.",
        }

    Verdict(**make_verdict(1))
    Verdict(**make_verdict(10))
    with pytest.raises(ValidationError):
        Verdict(**make_verdict(0))
    with pytest.raises(ValidationError):
        Verdict(**make_verdict(11))


def test_commentary_word_count_valid():
    commentary = " ".join(["word"] * 80)
    rec = PillarRecommendation(
        pillar_id="P1",
        suggested_commentary=commentary,
        recommendations=[
            Recommendation(action="Do something.", owner_role="PM", urgency="immediate", item_ids=["P1.1"]),
            Recommendation(action="Do another thing.", owner_role="Tech Lead", urgency="monitor", item_ids=["P1.2"]),
        ],
        manager_prompts=["What is the status?"],
    )
    assert rec.suggested_commentary == commentary


def test_commentary_too_short():
    commentary = "Too short."
    with pytest.raises(ValidationError, match="60-120 words"):
        PillarRecommendation(
            pillar_id="P1",
            suggested_commentary=commentary,
            recommendations=[
                Recommendation(action="Do something.", owner_role="PM", urgency="immediate", item_ids=["P1.1"]),
                Recommendation(action="Do another.", owner_role="TL", urgency="monitor", item_ids=["P1.2"]),
            ],
            manager_prompts=["Question?"],
        )


def test_commentary_too_long():
    commentary = " ".join(["word"] * 130)
    with pytest.raises(ValidationError, match="60-120 words"):
        PillarRecommendation(
            pillar_id="P1",
            suggested_commentary=commentary,
            recommendations=[
                Recommendation(action="Do something.", owner_role="PM", urgency="immediate", item_ids=["P1.1"]),
                Recommendation(action="Do another.", owner_role="TL", urgency="monitor", item_ids=["P1.2"]),
            ],
            manager_prompts=["Question?"],
        )
