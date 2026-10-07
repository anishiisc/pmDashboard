from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

# ── Shared types ────────────────────────────────────────────────────────────────

Rating = Literal["Good", "Medium", "Poor", "Not Evidenced"]
ItemId = Literal["P1.1", "P1.2", "P1.3", "P2.1", "P2.2", "P2.3", "P3.1", "P3.2", "P3.3"]
ALL_ITEM_IDS: list[str] = ["P1.1", "P1.2", "P1.3", "P2.1", "P2.2", "P2.3", "P3.1", "P3.2", "P3.3"]

_LINE_REF_RE = re.compile(r"^D\d+:L\d{3,}$")


class Quote(BaseModel):
    ref: str
    text: str = Field(max_length=400)

    @field_validator("ref")
    @classmethod
    def validate_ref(cls, v: str) -> str:
        if not _LINE_REF_RE.match(v):
            raise ValueError(f"Invalid line reference format: {v!r}. Expected D<n>:L<nnn>")
        return v


# ── S1: Extraction ───────────────────────────────────────────────────────────────

class IntegrityFlag(BaseModel):
    ref: str
    description: str

    @field_validator("ref")
    @classmethod
    def validate_ref(cls, v: str) -> str:
        if not _LINE_REF_RE.match(v):
            raise ValueError(f"Invalid line reference format: {v!r}")
        return v


class ExtractedItem(BaseModel):
    item_id: ItemId
    rating: Rating
    evidence: list[Quote] = Field(max_length=4)
    counter_evidence: list[Quote] = Field(default_factory=list, max_length=3)
    rationale: str = Field(max_length=500)

    @model_validator(mode="after")
    def evidence_required_unless_not_evidenced(self) -> "ExtractedItem":
        if self.rating != "Not Evidenced" and len(self.evidence) == 0:
            raise ValueError(
                f"Item {self.item_id}: evidence must be non-empty when rating is not 'Not Evidenced'"
            )
        return self


class ExtractionOutput(BaseModel):
    items: list[ExtractedItem] = Field(min_length=9, max_length=9)
    integrity_flags: list[IntegrityFlag] = Field(default_factory=list)

    @model_validator(mode="after")
    def all_item_ids_present_once(self) -> "ExtractionOutput":
        ids = [item.item_id for item in self.items]
        if sorted(ids) != sorted(ALL_ITEM_IDS):
            raise ValueError(
                f"Items must contain exactly one of each ID. Got: {ids}"
            )
        return self


# ── S3: Debate ───────────────────────────────────────────────────────────────────

class Challenge(BaseModel):
    item_id: ItemId
    stance: Literal["concur", "challenge"]
    proposed_rating: Rating | None = None
    failure_modes: list[int] = Field(default_factory=list)
    counter_evidence: list[Quote] = Field(default_factory=list)
    argument: str = Field(default="", max_length=600)


class ChallengeOutput(BaseModel):
    challenges: list[Challenge] = Field(min_length=9, max_length=9)

    @model_validator(mode="after")
    def all_item_ids_present_once(self) -> "ChallengeOutput":
        ids = [c.item_id for c in self.challenges]
        if sorted(ids) != sorted(ALL_ITEM_IDS):
            raise ValueError(f"Challenges must cover all 9 items exactly once. Got: {ids}")
        return self


class Rebuttal(BaseModel):
    item_id: ItemId
    response: Literal["concede", "rebut"]
    evidence: list[Quote] = Field(default_factory=list)
    argument: str = Field(max_length=600)


class RebuttalOutput(BaseModel):
    rebuttals: list[Rebuttal]


class Verdict(BaseModel):
    item_id: ItemId
    draft_rating: Rating
    final_rating: Rating
    verification_score: int = Field(ge=1, le=10)
    verdict: Literal["upheld", "revised", "set_not_evidenced"]
    evidence: list[Quote]
    reasoning: str = Field(max_length=600)


class VerdictOutput(BaseModel):
    verdicts: list[Verdict] = Field(min_length=9, max_length=9)

    @model_validator(mode="after")
    def all_item_ids_present_once(self) -> "VerdictOutput":
        ids = [v.item_id for v in self.verdicts]
        if sorted(ids) != sorted(ALL_ITEM_IDS):
            raise ValueError(f"Verdicts must cover all 9 items exactly once. Got: {ids}")
        return self


# ── S5: Recommendations ──────────────────────────────────────────────────────────

class Recommendation(BaseModel):
    action: str = Field(max_length=200)
    owner_role: str
    urgency: Literal["immediate", "this_month", "monitor"]
    item_ids: list[ItemId]


def _word_count(text: str) -> int:
    return len(text.split())


class PillarRecommendation(BaseModel):
    pillar_id: Literal["P1", "P2", "P3"]
    suggested_commentary: str = Field(max_length=900)
    recommendations: list[Recommendation] = Field(min_length=2, max_length=4)
    manager_prompts: list[str] = Field(min_length=1, max_length=3)

    @field_validator("suggested_commentary")
    @classmethod
    def commentary_word_count(cls, v: str) -> str:
        wc = _word_count(v)
        if not (60 <= wc <= 120):
            raise ValueError(
                f"suggested_commentary must be 60-120 words, got {wc}"
            )
        return v


class RecommendationOutput(BaseModel):
    pillars: list[PillarRecommendation] = Field(min_length=3, max_length=3)

    @model_validator(mode="after")
    def all_pillar_ids_present_once(self) -> "RecommendationOutput":
        ids = [p.pillar_id for p in self.pillars]
        if sorted(ids) != ["P1", "P2", "P3"]:
            raise ValueError(f"Recommendations must cover P1, P2, P3 exactly once. Got: {ids}")
        return self
