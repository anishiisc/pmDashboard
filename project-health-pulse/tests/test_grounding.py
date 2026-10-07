from __future__ import annotations

from app.pipeline.grounding import run_grounding
from app.schemas import ExtractionOutput, ExtractedItem, Quote


def _make_doc(doc_id: str, lines: list[str]) -> dict:
    return {
        "doc_id": doc_id,
        "body_lines": lines,
    }


def _make_extraction(items_data: list[dict]) -> ExtractionOutput:
    all_ids = ["P1.1", "P1.2", "P1.3", "P2.1", "P2.2", "P2.3", "P3.1", "P3.2", "P3.3"]
    items = []
    for item_id in all_ids:
        d = next((x for x in items_data if x["item_id"] == item_id), None)
        if d:
            items.append(ExtractedItem(**d))
        else:
            items.append(
                ExtractedItem(
                    item_id=item_id,
                    rating="Not Evidenced",
                    evidence=[],
                    rationale="No evidence found.",
                )
            )
    return ExtractionOutput(items=items)


def test_exact_match_grounded():
    doc = _make_doc("D1", ["[00:01:00] Alice: Milestone M2 is on track for the twelfth."])
    extraction = _make_extraction(
        [
            {
                "item_id": "P1.1",
                "rating": "Good",
                "evidence": [Quote(ref="D1:L001", text="Milestone M2 is on track for the twelfth.")],
                "rationale": "On track per Alice.",
            }
        ]
    )
    report = run_grounding(extraction, [doc])
    assert report["items"]["P1.1"]["quotes"][0]["grounded"] is True
    assert report["items"]["P1.1"]["ungrounded"] is False


def test_near_match_grounded():
    doc = _make_doc(
        "D1", ["[00:01:00] Alice: UAT came back with nineteen open defects, three critical."]
    )
    extraction = _make_extraction(
        [
            {
                "item_id": "P2.2",
                "rating": "Poor",
                "evidence": [
                    Quote(
                        ref="D1:L001",
                        text="UAT came back with nineteen open, three of them critical.",
                    )
                ],
                "rationale": "Rising defects.",
            }
        ]
    )
    report = run_grounding(extraction, [doc])
    # rapidfuzz partial_ratio should still score high for similar text
    assert report["items"]["P2.2"]["quotes"][0]["grounded"] is True


def test_fabricated_quote_marked_ungrounded():
    doc = _make_doc("D1", ["[00:01:00] Alice: Everything is going well today."])
    extraction = _make_extraction(
        [
            {
                "item_id": "P1.1",
                "rating": "Good",
                "evidence": [
                    Quote(
                        ref="D1:L001",
                        text="We delivered M2 three weeks ahead of schedule with zero defects.",
                    )
                ],
                "rationale": "Fabricated.",
            }
        ]
    )
    report = run_grounding(extraction, [doc])
    assert report["items"]["P1.1"]["ungrounded"] is True
    assert report["items"]["P1.1"]["quotes"][0]["grounded"] is False


def test_citation_correction():
    doc = _make_doc(
        "D1",
        [
            "[00:01:00] Alice: Nothing here.",
            "[00:02:00] Alice: The firewall blocker has been cleared on time.",
        ],
    )
    extraction = _make_extraction(
        [
            {
                "item_id": "P1.2",
                "rating": "Good",
                "evidence": [
                    Quote(
                        ref="D1:L001",  # Wrong line
                        text="The firewall blocker has been cleared on time.",
                    )
                ],
                "rationale": "Blocker cleared.",
            }
        ]
    )
    report = run_grounding(extraction, [doc])
    q = report["items"]["P1.2"]["quotes"][0]
    assert q["grounded"] is True
    assert q["citation_corrected"] is True
    assert q["ref"] == "D1:L002"
    assert q["original_ref"] == "D1:L001"
