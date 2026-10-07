from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import BackgroundTasks, FastAPI, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app import settings
from app.orchestrator import run_pipeline
from app.storage import get_run_dir, read_json, write_json

app = FastAPI(title="Project Health Pulse")

# Serve frontend static files
_frontend = Path(__file__).parent.parent / "frontend"
app.mount("/static", StaticFiles(directory=str(_frontend)), name="static")


@app.get("/")
async def index():
    return FileResponse(str(_frontend / "index.html"))


@app.get("/api/config/pillars")
async def get_pillars():
    pillar_path = settings.CONFIG_DIR / "pillars.json"
    return JSONResponse(content=json.loads(pillar_path.read_text()))


@app.post("/api/runs", status_code=202)
async def create_run(
    background_tasks: BackgroundTasks,
    files: list[UploadFile],
):
    if not files:
        raise HTTPException(status_code=400, detail="No files uploaded")
    if len(files) > settings.MAX_FILES:
        raise HTTPException(
            status_code=400,
            detail=f"Too many files: max {settings.MAX_FILES}",
        )

    # Generate run_id
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%S")
    short = uuid.uuid4().hex[:4]
    run_id = f"{ts}_{short}"

    # Stage uploads
    run_upload_dir = settings.UPLOADS_DIR / run_id
    run_upload_dir.mkdir(parents=True)

    total_chars = 0
    staged: list[dict] = []
    for upload in files:
        if not upload.filename or not upload.filename.endswith(".txt"):
            raise HTTPException(
                status_code=400,
                detail=f"Only .txt files accepted: {upload.filename}",
            )
        raw = await upload.read()
        size_kb = len(raw) / 1024
        if size_kb > settings.MAX_FILE_KB:
            raise HTTPException(
                status_code=400,
                detail=f"{upload.filename} exceeds {settings.MAX_FILE_KB} KB limit",
            )
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            try:
                text = raw.decode("latin-1")
            except Exception:
                raise HTTPException(
                    status_code=400,
                    detail=f"Cannot decode {upload.filename} as UTF-8 or latin-1",
                )
        total_chars += len(text)
        if total_chars > settings.MAX_TOTAL_CHARS:
            raise HTTPException(
                status_code=400,
                detail=f"Total character limit ({settings.MAX_TOTAL_CHARS}) exceeded",
            )
        dest = run_upload_dir / upload.filename
        dest.write_text(text, encoding="utf-8")
        staged.append({"filename": upload.filename, "path": str(dest)})

    # Initialise output folder and status
    run_out_dir = get_run_dir(run_id)
    write_json(run_out_dir / "status.json", {"state": "queued", "stage": None, "message": "Queued"})

    background_tasks.add_task(run_pipeline, run_id, staged)

    return JSONResponse(content={"run_id": run_id}, status_code=202)


@app.get("/api/runs/{run_id}/status")
async def run_status(run_id: str):
    run_dir = get_run_dir(run_id)
    status_file = run_dir / "status.json"
    if not status_file.exists():
        raise HTTPException(status_code=404, detail="Run not found")
    return JSONResponse(content=read_json(status_file))


@app.get("/api/runs/{run_id}/final")
async def run_final(run_id: str):
    run_dir = get_run_dir(run_id)
    final_file = run_dir / "final.json"
    if not final_file.exists():
        raise HTTPException(status_code=404, detail="Final output not yet available")
    return JSONResponse(content=read_json(final_file))


@app.get("/api/runs")
async def list_runs():
    outputs = settings.OUTPUTS_DIR
    runs = []
    for entry in sorted(outputs.iterdir(), reverse=True):
        if not entry.is_dir():
            continue
        final = entry / "final.json"
        if not final.exists():
            continue
        data = read_json(final)
        runs.append(
            {
                "run_id": data.get("run_id"),
                "created_at": data.get("created_at"),
                "file_count": len(data.get("source_documents", [])),
                "overall_rating": data.get("summary", {}).get("overall_rating"),
            }
        )
    return JSONResponse(content=runs)


@app.get("/api/runs/latest")
async def latest_run():
    latest_ptr = settings.OUTPUTS_DIR / "latest.json"
    if not latest_ptr.exists():
        raise HTTPException(status_code=404, detail="No runs yet")
    ptr = read_json(latest_ptr)
    run_id = ptr.get("run_id")
    run_dir = get_run_dir(run_id)
    final_file = run_dir / "final.json"
    if not final_file.exists():
        raise HTTPException(status_code=404, detail="Latest run not complete")
    return JSONResponse(content=read_json(final_file))


@app.post("/api/reset")
async def reset():
    import shutil
    upload_root = settings.UPLOADS_DIR
    if upload_root.exists():
        shutil.rmtree(upload_root)
    upload_root.mkdir(exist_ok=True)
    return JSONResponse(content={"ok": True})
