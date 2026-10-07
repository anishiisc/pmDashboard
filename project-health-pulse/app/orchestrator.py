from __future__ import annotations

import hashlib
import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path

from app import settings
from app.pipeline.assemble import assemble_final
from app.pipeline.debate import run_debate
from app.pipeline.extract import run_extraction
from app.pipeline.grounding import run_grounding
from app.pipeline.ingest import ingest_files
from app.pipeline.recommend import run_recommend
from app.pipeline.rollup import compute_overall_rating, run_rollup
from app.storage import get_run_dir, write_json

logger = logging.getLogger(__name__)


def _set_status(run_dir: Path, state: str, stage: str | None, message: str) -> None:
    write_json(run_dir / "status.json", {"state": state, "stage": stage, "message": message})


def _file_hash(path: str) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()[:12]


def run_pipeline(run_id: str, staged_files: list[dict]) -> None:
    run_dir = get_run_dir(run_id)
    log_path = run_dir / "run.log"
    logging.basicConfig(
        filename=str(log_path),
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    total_usage: dict = {}
    stage_latency: dict = {}
    start_total = time.time()

    try:
        # ── S0: Ingest ────────────────────────────────────────────────────────
        _set_status(run_dir, "running", "S0_ingest", "Ingesting transcripts")
        t0 = time.time()
        pillar_path = settings.CONFIG_DIR / "pillars.json"
        rubric_json = pillar_path.read_text(encoding="utf-8")

        document_index, transcripts, parsed_docs = ingest_files(staged_files)
        stage_latency["S0_ingest_ms"] = int((time.time() - t0) * 1000)
        write_json(run_dir / "01_ingest.json", {"documents": document_index})

        # Manifest
        manifest = {
            "run_id": run_id,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "model_extractor": settings.MODEL_EXTRACTOR,
            "model_challenger": settings.MODEL_CHALLENGER,
            "model_defender": settings.MODEL_DEFENDER,
            "model_judge": settings.MODEL_JUDGE,
            "model_recommender": settings.MODEL_RECOMMENDER,
            "debate_rounds": settings.DEBATE_ROUNDS,
            "review_threshold": settings.REVIEW_THRESHOLD,
            "grounding_min_similarity": settings.GROUNDING_MIN_SIMILARITY,
            "files": [
                {"filename": f["filename"], "sha256": _file_hash(f["path"])}
                for f in staged_files
            ],
        }
        write_json(run_dir / "00_manifest.json", manifest)

        # ── S1: Extract ───────────────────────────────────────────────────────
        _set_status(run_dir, "running", "S1_extract", "Extracting ratings from transcripts")
        t0 = time.time()
        extraction, usage_e = run_extraction(rubric_json, transcripts)
        stage_latency["S1_extract_ms"] = int((time.time() - t0) * 1000)
        _add_usage(total_usage, usage_e)
        write_json(run_dir / "02_extraction.json", extraction.model_dump())

        # ── S2: Grounding ─────────────────────────────────────────────────────
        _set_status(run_dir, "running", "S2_grounding", "Verifying quote citations")
        t0 = time.time()
        grounding_report = run_grounding(extraction, parsed_docs)
        stage_latency["S2_grounding_ms"] = int((time.time() - t0) * 1000)
        write_json(run_dir / "03_grounding.json", grounding_report)

        # ── S3: Debate ────────────────────────────────────────────────────────
        _set_status(run_dir, "running", "S3_debate", "Running adversarial review")
        t0 = time.time()
        challenges, rebuttals, verdicts, usage_d = run_debate(
            rubric_json, transcripts, extraction, grounding_report
        )
        stage_latency["S3_debate_ms"] = int((time.time() - t0) * 1000)
        _add_usage(total_usage, usage_d)
        write_json(
            run_dir / "04_debate.json",
            {
                "challenges": challenges.model_dump(),
                "rebuttals": rebuttals.model_dump() if rebuttals else None,
            },
        )
        write_json(run_dir / "05_final_assessment.json", verdicts.model_dump())

        # ── S4: Rollup ────────────────────────────────────────────────────────
        _set_status(run_dir, "running", "S4_rollup", "Computing pillar ratings")
        t0 = time.time()
        pillar_rollup = run_rollup(verdicts)
        overall_rating = compute_overall_rating(pillar_rollup)
        stage_latency["S4_rollup_ms"] = int((time.time() - t0) * 1000)

        # ── S5: Recommend ─────────────────────────────────────────────────────
        _set_status(run_dir, "running", "S5_recommend", "Drafting recommendations")
        t0 = time.time()
        recommendations, usage_r = run_recommend(
            rubric_json, transcripts, verdicts, pillar_rollup
        )
        stage_latency["S5_recommend_ms"] = int((time.time() - t0) * 1000)
        _add_usage(total_usage, usage_r)
        write_json(run_dir / "06_recommendations.json", recommendations.model_dump())

        # ── S6: Assemble ──────────────────────────────────────────────────────
        _set_status(run_dir, "running", "S6_assemble", "Assembling final report")
        total_usage["stage_latency_ms"] = stage_latency
        total_usage["total_ms"] = int((time.time() - start_total) * 1000)

        final = assemble_final(
            run_id=run_id,
            run_dir=run_dir,
            document_index=document_index,
            extraction=extraction,
            grounding_report=grounding_report,
            challenges=challenges,
            rebuttals=rebuttals,
            verdicts=verdicts,
            pillar_rollup=pillar_rollup,
            recommendations=recommendations,
            total_usage=total_usage,
            overall_rating=overall_rating,
        )

        # Update latest pointer
        write_json(settings.OUTPUTS_DIR / "latest.json", {"run_id": run_id})
        _set_status(run_dir, "complete", "S6_assemble", "Complete")
        logger.info("Run %s completed. Overall rating: %s", run_id, overall_rating)

    except Exception as exc:  # noqa: BLE001
        logger.exception("Run %s failed", run_id)
        _set_status(
            run_dir,
            "failed",
            None,
            f"Pipeline failed: {type(exc).__name__}: {exc}",
        )


def _add_usage(combined: dict, new: dict) -> None:
    for k, v in new.items():
        if isinstance(v, (int, float)):
            combined[k] = combined.get(k, 0) + v
        elif k not in combined:
            combined[k] = v
