from __future__ import annotations

import json

from app import settings
from app.llm import call_structured, cached_content_blocks, load_prompt
from app.schemas import (
    ChallengeOutput,
    ExtractionOutput,
    RebuttalOutput,
    VerdictOutput,
)


def run_debate(
    rubric_json: str,
    transcripts: str,
    extraction: ExtractionOutput,
    grounding_report: dict,
) -> tuple[ChallengeOutput, RebuttalOutput | None, VerdictOutput, dict]:
    """
    S3: Adversarial debate — Challenger → Defender → Judge.

    Returns (challenges, rebuttals_or_None, verdicts, combined_usage).
    """
    combined_usage: dict = {}
    draft_json = extraction.model_dump_json(indent=2)
    grounding_json = json.dumps(grounding_report, indent=2)

    # ── 3a: Challenger ────────────────────────────────────────────────────────
    challenger_system = load_prompt("challenger_system.md")
    challenger_blocks = cached_content_blocks(rubric_json, transcripts) + [
        {"type": "text", "text": f"<draft_assessment>{draft_json}</draft_assessment>\n<grounding_report>{grounding_json}</grounding_report>"},
    ]

    challenges, usage_c = call_structured(
        model=settings.MODEL_CHALLENGER,
        system=challenger_system,
        user_blocks=challenger_blocks,
        tool_name="submit_challenges",
        schema_model=ChallengeOutput,
        temperature=0.3,
    )
    _add_usage(combined_usage, usage_c)

    challenged_items = [c for c in challenges.challenges if c.stance == "challenge"]
    challenges_json = challenges.model_dump_json(indent=2)

    # ── 3b: Defender (only if there are challenges) ───────────────────────────
    rebuttals: RebuttalOutput | None = None
    rebuttals_json = "[]"
    if challenged_items:
        defender_system = load_prompt("defender_system.md")
        defender_blocks = cached_content_blocks(rubric_json, transcripts) + [
            {"type": "text", "text": (
                f"<draft_assessment>{draft_json}</draft_assessment>\n"
                f"<challenges>{challenges_json}</challenges>"
            )},
        ]

        rebuttals, usage_d = call_structured(
            model=settings.MODEL_DEFENDER,
            system=defender_system,
            user_blocks=defender_blocks,
            tool_name="submit_rebuttals",
            schema_model=RebuttalOutput,
            temperature=0,
        )
        _add_usage(combined_usage, usage_d)
        rebuttals_json = rebuttals.model_dump_json(indent=2)

    # ── 3c: Judge ─────────────────────────────────────────────────────────────
    judge_system = load_prompt("judge_system.md")
    judge_blocks = cached_content_blocks(rubric_json, transcripts) + [
        {"type": "text", "text": (
            f"<draft_assessment>{draft_json}</draft_assessment>\n"
            f"<grounding_report>{grounding_json}</grounding_report>\n"
            f"<challenges>{challenges_json}</challenges>\n"
            f"<rebuttals>{rebuttals_json}</rebuttals>"
        )},
    ]

    verdicts, usage_j = call_structured(
        model=settings.MODEL_JUDGE,
        system=judge_system,
        user_blocks=judge_blocks,
        tool_name="submit_verdicts",
        schema_model=VerdictOutput,
        temperature=0,
    )
    _add_usage(combined_usage, usage_j)

    return challenges, rebuttals, verdicts, combined_usage


def _add_usage(combined: dict, new: dict) -> None:
    for k, v in new.items():
        if isinstance(v, (int, float)):
            combined[k] = combined.get(k, 0) + v
        elif k not in combined:
            combined[k] = v
