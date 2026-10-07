from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any

import anthropic
from pydantic import BaseModel, ValidationError

from app import settings

logger = logging.getLogger(__name__)

_client: anthropic.Anthropic | None = None


def get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        _client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)
    return _client


def load_prompt(name: str, **substitutions: str) -> str:
    """Load a prompt file from prompts/ and fill {{PLACEHOLDER}} tokens."""
    path = settings.PROMPTS_DIR / name
    text = path.read_text(encoding="utf-8")
    for key, value in substitutions.items():
        text = text.replace(f"{{{{{key}}}}}", value)
    return text


def _tool_def(tool_name: str, schema_model: type[BaseModel]) -> dict:
    return {
        "name": tool_name,
        "description": f"Submit the {tool_name} result. Must be called exactly once.",
        "input_schema": schema_model.model_json_schema(),
    }


def call_structured(
    model: str,
    system: str,
    user_blocks: list[dict],
    tool_name: str,
    schema_model: type[BaseModel],
    temperature: float,
    max_tokens: int | None = None,
) -> tuple[BaseModel, dict]:
    """
    Make a forced-tool LLM call and validate the response with Pydantic.
    Retries once on validation failure (passes the error back to the model).
    Also retries on transient API errors with exponential back-off.

    Returns (validated_model_instance, usage_dict).
    """
    client = get_client()
    if max_tokens is None:
        max_tokens = settings.MAX_TOKENS_STAGE

    tool = _tool_def(tool_name, schema_model)
    messages: list[dict] = [{"role": "user", "content": user_blocks}]

    api_retries = settings.LLM_MAX_RETRIES
    backoff = 1.0

    for api_attempt in range(api_retries):
        try:
            resp = _api_call(client, model, system, messages, tool, tool_name, temperature, max_tokens)
            break
        except (
            anthropic.RateLimitError,
            anthropic.APIConnectionError,
            anthropic.InternalServerError,
        ) as exc:
            if api_attempt < api_retries - 1:
                logger.warning("API error (attempt %d/%d): %s — retrying in %.0fs", api_attempt + 1, api_retries, exc, backoff)
                time.sleep(backoff)
                backoff *= 2
            else:
                raise

    # Extract the tool-use block
    block = next((b for b in resp.content if b.type == "tool_use"), None)
    if block is None:
        raise RuntimeError(f"Model did not call tool {tool_name!r}")

    usage = _extract_usage(resp.usage)

    # Validation with one repair retry
    for validation_attempt in range(2):
        try:
            result = schema_model.model_validate(block.input)
            logger.info("Stage %s: model=%s tokens_in=%s tokens_out=%s",
                        tool_name, model, usage.get("input_tokens"), usage.get("output_tokens"))
            return result, usage
        except ValidationError as exc:
            if validation_attempt == 0:
                logger.warning("Validation failed for %s (attempt 1): %s", tool_name, exc)
                # Repair: send the error back to the model
                messages = messages + [
                    {"role": "assistant", "content": resp.content},
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "tool_result",
                                "tool_use_id": block.id,
                                "is_error": True,
                                "content": f"Validation failed: {exc}. Call {tool_name} again with corrected input.",
                            }
                        ],
                    },
                ]
                # Make another API call for the repair
                for api_attempt in range(api_retries):
                    try:
                        resp = _api_call(client, model, system, messages, tool, tool_name, temperature, max_tokens)
                        break
                    except (
                        anthropic.RateLimitError,
                        anthropic.APIConnectionError,
                        anthropic.InternalServerError,
                    ) as api_exc:
                        if api_attempt < api_retries - 1:
                            time.sleep(backoff)
                            backoff *= 2
                        else:
                            raise

                block = next((b for b in resp.content if b.type == "tool_use"), None)
                if block is None:
                    raise RuntimeError(f"Model did not call tool {tool_name!r} on repair attempt")
                # Accumulate usage (scalar fields only)
                for k, v in _extract_usage(resp.usage).items():
                    usage[k] = usage.get(k, 0) + v
            else:
                raise RuntimeError(f"{tool_name} failed validation twice: {exc}") from exc

    raise RuntimeError(f"{tool_name} failed unexpectedly")


def _api_call(
    client: anthropic.Anthropic,
    model: str,
    system: str,
    messages: list[dict],
    tool: dict,
    tool_name: str,
    temperature: float,
    max_tokens: int,
) -> Any:
    return client.messages.create(
        model=model,
        system=system,
        messages=messages,
        tools=[tool],
        tool_choice={"type": "tool", "name": tool_name},
        temperature=temperature,
        max_tokens=max_tokens,
    )


def _extract_usage(usage_obj) -> dict:
    """Return only scalar integer token counts from the SDK Usage object.

    The SDK Usage model_dump() may include nested objects (cache_creation,
    output_tokens_details, server_tool_use) whose type changes across SDK
    versions. Summing dicts raises TypeError, so we only keep int/float fields.
    """
    raw = usage_obj.model_dump()
    return {k: v for k, v in raw.items() if isinstance(v, (int, float))}


def cached_content_blocks(rubric_json: str, transcripts: str) -> list[dict]:
    """
    Build the shared cached prefix block (rubric + transcripts).
    Subsequent stage-specific blocks are appended after this.
    """
    return [
        {
            "type": "text",
            "text": f"<rubric>{rubric_json}</rubric>\n<transcripts>{transcripts}</transcripts>",
            "cache_control": {"type": "ephemeral"},
        }
    ]
