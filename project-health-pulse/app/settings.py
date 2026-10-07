from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# Paths
BASE_DIR = Path(__file__).parent.parent
CONFIG_DIR = BASE_DIR / "config"
PROMPTS_DIR = BASE_DIR / "prompts"
UPLOADS_DIR = BASE_DIR / "uploads"
OUTPUTS_DIR = BASE_DIR / "outputs"

UPLOADS_DIR.mkdir(exist_ok=True)
OUTPUTS_DIR.mkdir(exist_ok=True)

# Models
MODEL_EXTRACTOR: str = os.getenv("MODEL_EXTRACTOR", "claude-sonnet-4-5")
MODEL_CHALLENGER: str = os.getenv("MODEL_CHALLENGER", "claude-sonnet-4-5")
MODEL_DEFENDER: str = os.getenv("MODEL_DEFENDER", "claude-sonnet-4-5")
MODEL_JUDGE: str = os.getenv("MODEL_JUDGE", "claude-opus-4-5")
MODEL_RECOMMENDER: str = os.getenv("MODEL_RECOMMENDER", "claude-sonnet-4-5")

# LLM limits
MAX_TOKENS_STAGE: int = int(os.getenv("MAX_TOKENS_STAGE", "8000"))
LLM_MAX_RETRIES: int = int(os.getenv("LLM_MAX_RETRIES", "3"))

# Pipeline params
DEBATE_ROUNDS: int = int(os.getenv("DEBATE_ROUNDS", "1"))
REVIEW_THRESHOLD: int = int(os.getenv("REVIEW_THRESHOLD", "6"))
GROUNDING_MIN_SIMILARITY: int = int(os.getenv("GROUNDING_MIN_SIMILARITY", "85"))

# Ingest limits
MAX_FILES: int = int(os.getenv("MAX_FILES", "10"))
MAX_FILE_KB: int = int(os.getenv("MAX_FILE_KB", "200"))
MAX_TOTAL_CHARS: int = int(os.getenv("MAX_TOTAL_CHARS", "300000"))

# Anthropic key (never log this)
ANTHROPIC_API_KEY: str = os.getenv("ANTHROPIC_API_KEY", "")
