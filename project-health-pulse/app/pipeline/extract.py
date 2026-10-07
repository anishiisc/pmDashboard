from __future__ import annotations

import json

from app import settings
from app.llm import call_structured, cached_content_blocks, load_prompt
from app.schemas import ExtractionOutput


def run_extraction(rubric_json: str, transcripts: str) -> tuple[ExtractionOutput, dict]:
    """
    S1: Call the extractor LLM with a forced tool to produce structured ratings.

    Returns (ExtractionOutput, usage_dict).
    """
    system = load_prompt("extractor_system.md", RUBRIC_JSON=rubric_json)
    user_blocks = cached_content_blocks(rubric_json, transcripts)

    result, usage = call_structured(
        model=settings.MODEL_EXTRACTOR,
        system=system,
        user_blocks=user_blocks,
        tool_name="submit_assessment",
        schema_model=ExtractionOutput,
        temperature=0,
    )
    return result, usage
