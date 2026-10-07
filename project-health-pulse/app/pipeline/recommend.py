from __future__ import annotations

import json

from app import settings
from app.llm import call_structured, cached_content_blocks, load_prompt
from app.schemas import RecommendationOutput, VerdictOutput


def run_recommend(
    rubric_json: str,
    transcripts: str,
    verdicts: VerdictOutput,
    pillar_rollup: list[dict],
) -> tuple[RecommendationOutput, dict]:
    """
    S5: Draft pillar commentary and recommendations.

    Returns (RecommendationOutput, usage_dict).
    """
    final_assessment_json = verdicts.model_dump_json(indent=2)
    rollup_json = json.dumps(pillar_rollup, indent=2)

    system = load_prompt(
        "recommender_system.md",
        REVIEW_THRESHOLD=str(settings.REVIEW_THRESHOLD),
    )

    user_blocks = cached_content_blocks(rubric_json, transcripts) + [
        {
            "type": "text",
            "text": (
                f"<final_assessment>{final_assessment_json}</final_assessment>\n"
                f"<rollup>{rollup_json}</rollup>"
            ),
        }
    ]

    result, usage = call_structured(
        model=settings.MODEL_RECOMMENDER,
        system=system,
        user_blocks=user_blocks,
        tool_name="submit_recommendations",
        schema_model=RecommendationOutput,
        temperature=0.2,
    )
    return result, usage
