from __future__ import annotations

import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.schemas import (
    ChallengeOutput,
    ExtractionOutput,
    Quote,
    RebuttalOutput,
    Recommendation,
    RecommendationOutput,
    PillarRecommendation,
    VerdictOutput,
    Verdict,
    Challenge,
    ExtractedItem,
    IntegrityFlag,
)

ALL_ITEM_IDS = ["P1.1", "P1.2", "P1.3", "P2.1", "P2.2", "P2.3", "P3.1", "P3.2", "P3.3"]


def _make_extraction() -> ExtractionOutput:
    items = []
    for i, item_id in enumerate(ALL_ITEM_IDS):
        rating = "Poor" if item_id in ("P1.1", "P3.2") else "Good"
        items.append(
            ExtractedItem(
                item_id=item_id,
                rating=rating,
                evidence=[Quote(ref=f"D1:L00{i+1}", text=f"Evidence for {item_id}.")],
                rationale=f"Test rationale for {item_id}.",
            )
        )
    flags = [IntegrityFlag(ref="D4:L037", description="Injection attempt detected.")]
    return ExtractionOutput(items=items, integrity_flags=flags)


def _make_challenges() -> ChallengeOutput:
    challenges = []
    for item_id in ALL_ITEM_IDS:
        challenges.append(
            Challenge(
                item_id=item_id,
                stance="concur",
                proposed_rating=None,
                failure_modes=[],
                counter_evidence=[],
                argument="",
            )
        )
    return ChallengeOutput(challenges=challenges)


def _make_verdicts(extraction: ExtractionOutput) -> VerdictOutput:
    verdicts = []
    for item in extraction.items:
        verdicts.append(
            Verdict(
                item_id=item.item_id,
                draft_rating=item.rating,
                final_rating=item.rating,
                verification_score=8,
                verdict="upheld",
                evidence=item.evidence,
                reasoning="Judge upheld the draft rating.",
            )
        )
    return VerdictOutput(verdicts=verdicts)


def _make_recommendations() -> RecommendationOutput:
    word = "word "
    commentary = (word * 70).strip()  # 70 words

    pillars = []
    for pid in ["P1", "P2", "P3"]:
        pillars.append(
            PillarRecommendation(
                pillar_id=pid,
                suggested_commentary=commentary,
                recommendations=[
                    Recommendation(
                        action="Take immediate action on priority items.",
                        owner_role="Engagement Manager",
                        urgency="immediate",
                        item_ids=[f"{pid}.1"],
                    ),
                    Recommendation(
                        action="Monitor risk register weekly.",
                        owner_role="Tech Lead",
                        urgency="monitor",
                        item_ids=[f"{pid}.2"],
                    ),
                ],
                manager_prompts=["Has the situation improved since the last call?"],
            )
        )
    return RecommendationOutput(pillars=pillars)


VALID_TRANSCRIPT = """\
MEETING: Test Meeting
DATE: 2026-09-01
ATTENDEES: Alice (PM, Delivery); Bob (Tech, Client)
---
[00:00:01] Alice (PM): Good morning.
[00:00:05] Bob (Tech): Morning.
[00:00:10] Alice (PM): Let's get started.
[00:00:20] Alice (PM): M2 is on track.
[00:00:30] Bob (Tech): Defects are under control.
"""


def _setup_run(tmp_path: Path) -> tuple[str, list[dict]]:
    """Create a run directory and staged files."""
    import app.settings as s
    run_id = "test-run-001"
    upload_dir = tmp_path / "uploads" / run_id
    upload_dir.mkdir(parents=True)
    output_dir = tmp_path / "outputs"
    output_dir.mkdir(parents=True)

    txt = upload_dir / "t1.txt"
    txt.write_text(VALID_TRANSCRIPT)
    staged = [{"filename": "t1.txt", "path": str(txt)}]
    return run_id, staged


@patch("app.orchestrator.run_recommend")
@patch("app.orchestrator.run_debate")
@patch("app.orchestrator.run_extraction")
def test_pipeline_writes_all_outputs(mock_extract, mock_debate, mock_recommend, tmp_path):
    extraction = _make_extraction()
    challenges = _make_challenges()
    verdicts = _make_verdicts(extraction)
    recs = _make_recommendations()

    mock_extract.return_value = (extraction, {"input_tokens": 100, "output_tokens": 50})
    mock_debate.return_value = (challenges, None, verdicts, {"input_tokens": 200, "output_tokens": 80})
    mock_recommend.return_value = (recs, {"input_tokens": 150, "output_tokens": 60})

    with patch("app.settings.UPLOADS_DIR", tmp_path / "uploads"), \
         patch("app.settings.OUTPUTS_DIR", tmp_path / "outputs"), \
         patch("app.settings.CONFIG_DIR", Path("config")):

        from app.orchestrator import run_pipeline
        run_id, staged = _setup_run(tmp_path)
        run_pipeline(run_id, staged)

    out_dir = tmp_path / "outputs" / run_id
    required_files = [
        "00_manifest.json",
        "01_ingest.json",
        "02_extraction.json",
        "03_grounding.json",
        "04_debate.json",
        "05_final_assessment.json",
        "06_recommendations.json",
        "final.json",
        "status.json",
    ]
    for fname in required_files:
        assert (out_dir / fname).exists(), f"Missing: {fname}"

    status = json.loads((out_dir / "status.json").read_text())
    assert status["state"] == "complete"

    final = json.loads((out_dir / "final.json").read_text())
    assert final["run_id"] == run_id
    assert "pillars" in final
    assert len(final["pillars"]) == 3
    assert final["summary"]["overall_rating"] in ("Good", "Medium", "Poor", "Not Evidenced")


@patch("app.orchestrator.run_recommend")
@patch("app.orchestrator.run_debate")
@patch("app.orchestrator.run_extraction")
def test_pipeline_sets_failed_on_exception(mock_extract, mock_debate, mock_recommend, tmp_path):
    mock_extract.side_effect = RuntimeError("Simulated API failure")
    mock_debate.return_value = (None, None, None, {})
    mock_recommend.return_value = (None, {})

    with patch("app.settings.UPLOADS_DIR", tmp_path / "uploads"), \
         patch("app.settings.OUTPUTS_DIR", tmp_path / "outputs"), \
         patch("app.settings.CONFIG_DIR", Path("config")):

        from app.orchestrator import run_pipeline
        run_id, staged = _setup_run(tmp_path)
        run_pipeline(run_id, staged)

    out_dir = tmp_path / "outputs" / run_id
    status = json.loads((out_dir / "status.json").read_text())
    assert status["state"] == "failed"
    assert "Simulated API failure" in status["message"]


@patch("app.orchestrator.run_recommend")
@patch("app.orchestrator.run_debate")
@patch("app.orchestrator.run_extraction")
def test_integrity_flags_in_final(mock_extract, mock_debate, mock_recommend, tmp_path):
    extraction = _make_extraction()  # includes the injection flag
    challenges = _make_challenges()
    verdicts = _make_verdicts(extraction)
    recs = _make_recommendations()

    mock_extract.return_value = (extraction, {})
    mock_debate.return_value = (challenges, None, verdicts, {})
    mock_recommend.return_value = (recs, {})

    with patch("app.settings.UPLOADS_DIR", tmp_path / "uploads"), \
         patch("app.settings.OUTPUTS_DIR", tmp_path / "outputs"), \
         patch("app.settings.CONFIG_DIR", Path("config")):

        from app.orchestrator import run_pipeline
        run_id, staged = _setup_run(tmp_path)
        run_pipeline(run_id, staged)

    final = json.loads((tmp_path / "outputs" / run_id / "final.json").read_text())
    flags = final.get("integrity_flags", [])
    assert len(flags) == 1
    assert "Injection" in flags[0]["description"]
