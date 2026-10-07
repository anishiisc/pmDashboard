from __future__ import annotations

import json
from pathlib import Path

from app import settings


def get_run_dir(run_id: str) -> Path:
    run_dir = settings.OUTPUTS_DIR / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    return run_dir


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: dict | list) -> None:
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
