from __future__ import annotations

from rapidfuzz import fuzz

from app import settings
from app.schemas import ExtractionOutput


def _build_line_lookup(parsed_docs: list[dict]) -> dict[str, str]:
    """Build a flat mapping: 'D1:L001' -> raw line text."""
    lookup: dict[str, str] = {}
    for doc in parsed_docs:
        doc_id = doc["doc_id"]
        for j, line in enumerate(doc["body_lines"], start=1):
            ref = f"{doc_id}:L{j:03d}"
            lookup[ref] = line
    return lookup


def _best_match(quote_text: str, lookup: dict[str, str]) -> tuple[str, float]:
    """Find the best-matching line across all documents. Returns (ref, score)."""
    best_ref = ""
    best_score = 0.0
    for ref, line in lookup.items():
        score = fuzz.partial_ratio(quote_text, line)
        if score > best_score:
            best_score = score
            best_ref = ref
    return best_ref, best_score


def run_grounding(
    extraction: ExtractionOutput,
    parsed_docs: list[dict],
) -> dict:
    """
    Check each evidence quote against the transcript line it claims to come from.
    Returns a grounding report dict and a mutated extraction dict with corrections applied.
    """
    lookup = _build_line_lookup(parsed_docs)
    threshold = settings.GROUNDING_MIN_SIMILARITY

    report: dict[str, dict] = {}

    for item in extraction.items:
        item_report: dict[str, list] = {"ungrounded": False, "quotes": []}
        grounded_count = 0

        for quote in item.evidence + item.counter_evidence:
            cited_line = lookup.get(quote.ref, "")
            score = fuzz.partial_ratio(quote.text, cited_line) if cited_line else 0.0
            quote_result: dict = {
                "ref": quote.ref,
                "grounded": False,
                "similarity": round(score, 1),
                "citation_corrected": False,
            }

            if score >= threshold:
                quote_result["grounded"] = True
                grounded_count += 1
            else:
                # Search all lines for a better match
                best_ref, best_score = _best_match(quote.text, lookup)
                if best_score >= threshold and best_ref != quote.ref:
                    # Correct the citation
                    quote_result["original_ref"] = quote.ref
                    quote_result["ref"] = best_ref
                    quote_result["similarity"] = round(best_score, 1)
                    quote_result["grounded"] = True
                    quote_result["citation_corrected"] = True
                    # Mutate the quote object reference in-memory
                    quote.ref = best_ref
                    grounded_count += 1
                else:
                    quote_result["grounded"] = False

            item_report["quotes"].append(quote_result)

        # Flag item as ungrounded if it has a rating but zero grounded quotes
        if item.rating != "Not Evidenced" and grounded_count == 0 and len(item.evidence) > 0:
            item_report["ungrounded"] = True

        report[item.item_id] = item_report

    return {"items": report}
