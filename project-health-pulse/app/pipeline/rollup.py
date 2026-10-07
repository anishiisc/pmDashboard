from __future__ import annotations

from app import settings
from app.schemas import ALL_ITEM_IDS, Rating, VerdictOutput

_PILLAR_ITEMS: dict[str, list[str]] = {
    "P1": ["P1.1", "P1.2", "P1.3"],
    "P2": ["P2.1", "P2.2", "P2.3"],
    "P3": ["P3.1", "P3.2", "P3.3"],
}

_SEVERITY: dict[str, int] = {"Poor": 3, "Medium": 2, "Good": 1, "Not Evidenced": 0}


def _worst_of(ratings: list[Rating]) -> Rating:
    """Worst-of rule over evidenced items."""
    evidenced = [r for r in ratings if r != "Not Evidenced"]
    if not evidenced:
        return "Not Evidenced"
    return max(evidenced, key=lambda r: _SEVERITY[r])


def run_rollup(verdicts: VerdictOutput) -> list[dict]:
    """
    Compute pillar ratings, confidence scores, coverage gaps, and review flags.
    Returns a list of pillar dicts.
    """
    verdict_map = {v.item_id: v for v in verdicts.verdicts}
    threshold = settings.REVIEW_THRESHOLD

    pillar_results: list[dict] = []

    for pillar_id, item_ids in _PILLAR_ITEMS.items():
        items_out: list[dict] = []
        ratings: list[Rating] = []
        scores: list[int] = []
        any_review_required = False

        for item_id in item_ids:
            v = verdict_map[item_id]
            ratings.append(v.final_rating)
            scores.append(v.verification_score)

            review = v.verification_score < threshold
            if review:
                any_review_required = True

            items_out.append(
                {
                    "item_id": v.item_id,
                    "final_rating": v.final_rating,
                    "draft_rating": v.draft_rating,
                    "verification_score": v.verification_score,
                    "verdict": v.verdict,
                    "manager_review_required": review,
                    "evidence": [e.model_dump() for e in v.evidence],
                    "reasoning": v.reasoning,
                }
            )

        pillar_rating = _worst_of(ratings)
        evidenced_ratings = [r for r in ratings if r != "Not Evidenced"]
        coverage_gap = len(evidenced_ratings) < len(ratings)  # at least one Not Evidenced

        if scores:
            confidence_mean = round(sum(scores) / len(scores), 1)
            confidence_min = min(scores)
        else:
            confidence_mean = 0.0
            confidence_min = 0

        pillar_results.append(
            {
                "pillar_id": pillar_id,
                "rating": pillar_rating,
                "confidence_mean": confidence_mean,
                "confidence_min": confidence_min,
                "coverage_gap": coverage_gap,
                "manager_review_required": any_review_required,
                "items": items_out,
            }
        )

    return pillar_results


def compute_overall_rating(pillar_results: list[dict]) -> Rating:
    """Overall project rating = worst pillar rating."""
    ratings: list[Rating] = [p["rating"] for p in pillar_results]
    return _worst_of(ratings)
