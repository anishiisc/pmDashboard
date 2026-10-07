from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from app.schemas import (
    ChallengeOutput,
    ExtractionOutput,
    RebuttalOutput,
    RecommendationOutput,
    VerdictOutput,
)
from app.storage import write_json


def assemble_final(
    run_id: str,
    run_dir: Path,
    document_index: list[dict],
    extraction: ExtractionOutput,
    grounding_report: dict,
    challenges: ChallengeOutput,
    rebuttals: RebuttalOutput | None,
    verdicts: VerdictOutput,
    pillar_rollup: list[dict],
    recommendations: RecommendationOutput,
    total_usage: dict,
    overall_rating: str,
) -> dict:
    """
    S6: Merge all stage outputs into final.json.
    """
    # Map recommendation data by pillar_id
    rec_by_pillar = {r.pillar_id: r for r in recommendations.pillars}
    challenge_by_item = {c.item_id: c for c in challenges.challenges}
    rebuttal_by_item = {rb.item_id: rb for rb in (rebuttals.rebuttals if rebuttals else [])}
    verdict_by_item = {v.item_id: v for v in verdicts.verdicts}

    # Find items flagged for review or changed by debate
    items_flagged = [
        v.item_id
        for rollup_pillar in pillar_rollup
        for item in rollup_pillar["items"]
        if item["manager_review_required"]
        for v in [verdict_by_item[item["item_id"]]]
    ]
    ratings_changed = [
        v.item_id
        for v in verdicts.verdicts
        if v.draft_rating != v.final_rating
    ]

    # Build pillars output
    pillars_out = []
    for rollup_pillar in pillar_rollup:
        pid = rollup_pillar["pillar_id"]
        rec = rec_by_pillar.get(pid)

        items_out = []
        for item in rollup_pillar["items"]:
            item_id = item["item_id"]
            v = verdict_by_item[item_id]
            ch = challenge_by_item.get(item_id)
            rb = rebuttal_by_item.get(item_id)

            debate_out: dict | None = None
            if ch:
                debate_out = {
                    "challenge": {
                        "stance": ch.stance,
                        "proposed_rating": ch.proposed_rating,
                        "failure_modes": ch.failure_modes,
                        "argument": ch.argument,
                        "counter_evidence": [e.model_dump() for e in ch.counter_evidence],
                    }
                }
                if rb:
                    debate_out["rebuttal"] = {
                        "response": rb.response,
                        "argument": rb.argument,
                        "evidence": [e.model_dump() for e in rb.evidence],
                    }

            # Find item name from rollup pillar
            items_out.append(
                {
                    "item_id": v.item_id,
                    "draft_rating": v.draft_rating,
                    "final_rating": v.final_rating,
                    "verification_score": v.verification_score,
                    "verdict": v.verdict,
                    "manager_review_required": item["manager_review_required"],
                    "evidence": [e.model_dump() for e in v.evidence],
                    "reasoning": v.reasoning,
                    "debate": debate_out,
                }
            )

        pillar_out = {
            "pillar_id": pid,
            "rating": rollup_pillar["rating"],
            "confidence_mean": rollup_pillar["confidence_mean"],
            "confidence_min": rollup_pillar["confidence_min"],
            "coverage_gap": rollup_pillar["coverage_gap"],
            "manager_review_required": rollup_pillar["manager_review_required"],
            "items": items_out,
        }
        if rec:
            pillar_out["suggested_commentary"] = rec.suggested_commentary
            pillar_out["recommendations"] = [r.model_dump() for r in rec.recommendations]
            pillar_out["manager_prompts"] = rec.manager_prompts

        pillars_out.append(pillar_out)

    final = {
        "run_id": run_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source_documents": document_index,
        "integrity_flags": [f.model_dump() for f in extraction.integrity_flags],
        "summary": {
            "overall_rating": overall_rating,
            "items_flagged_for_review": items_flagged,
            "ratings_changed_by_debate": ratings_changed,
        },
        "pillars": pillars_out,
        "usage": total_usage,
    }

    write_json(run_dir / "final.json", final)
    return final
