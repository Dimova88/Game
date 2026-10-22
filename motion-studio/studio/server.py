"""API local (FastAPI) + interfaz web estática."""

from __future__ import annotations

import shutil
import threading
import traceback
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import pipeline
from .config import (
    ASPECTS,
    DEFAULT_WHISPER_MODEL,
    LANGUAGES,
    RESOLUTIONS,
    WEB_DIR,
    WHISPER_MODELS,
    ffmpeg_path,
    llm_settings,
)
from .fonts import font_info
from .styles import STYLES

app = FastAPI(title="Motion Studio", version="0.1.0")
_jobs: dict[str, dict] = {}
_jobs_lock = threading.Lock()
# Un solo trabajo a la vez: la transcripción y el render consumen toda la CPU.
_executor = ThreadPoolExecutor(max_workers=1)
AUDIO_EXT = {".mp3", ".wav", ".m4a", ".aac", ".ogg", ".flac", ".opus", ".mp4", ".mov", ".webm", ".mkv"}
TRANSCRIPT_EXT = {".json", ".srt", ".vtt"}


def _set_job(jid: str, **kw) -> None:
    with _jobs_lock:
        _jobs[jid].update(kw)


def _start_job(kind: str, pid: str, fn, *args) -> str:
    jid = uuid.uuid4().hex[:10]
    with _jobs_lock:
        _jobs[jid] = {"id": jid, "kind": kind, "project_id": pid, "status": "queued", "stage": "En cola",
                      "progress": 0.0, "result": None, "error": None}

    def progress(stage: str, p: float) -> None:
        _set_job(jid, stage=stage, progress=round(min(1.0, max(0.0, p)), 4))

    def run():
        _set_job(jid, status="running", stage="Iniciando")
        try:
            result = fn(*args, progress)
            _set_job(jid, status="done", progress=1.0, stage="Completado", result=result)
        except Exception as exc:  # se muestra en la UI
            traceback.print_exc()
            _set_job(jid, status="error", error=str(exc) or exc.__class__.__name__, stage="Error")
            try:
                pdir = pipeline.project_dir(pid)
                proj = pipeline.load_project(pdir)
                proj["status"] = "error"
                proj["error"] = str(exc)
                pipeline.save_project(pdir, proj)
            except Exception:
                pass

    _executor.submit(run)
    return jid


class PlanEdit(BaseModel):
    id: int
    kind: str | None = None
    emphasis: list[str] | None = None


class PlanUpdate(BaseModel):
    scenes: list[PlanEdit] = Field(default_factory=list)


class RenderRequest(BaseModel):
    style: str = "neon_tech"
    aspect: str = "16:9"
    resolution: str = "1080p"
    fps: int = 30
    captions: bool = True


@app.get("/api/meta")
def meta():
    return {
        "styles": [s.public() for s in STYLES.values()],
        "whisper_models": WHISPER_MODELS,
        "default_whisper_model": DEFAULT_WHISPER_MODEL,
        "languages": LANGUAGES,
        "aspects": list(ASPECTS),
        "resolutions": list(RESOLUTIONS),
        "fps": [24, 30, 60],
        "llm_configured": llm_settings() is not None,
        "llm_model": (llm_settings() or {}).get("model"),
        "ffmpeg": ffmpeg_path(),
        "fonts": font_info(),
    }


@app.get("/api/projects")
def projects():
    return pipeline.list_projects()


@app.get("/api/projects/{pid}")
def project(pid: str):
    pdir = _pdir(pid)
    proj = pipeline.load_project(pdir)
    plan = pipeline.read_plan(pdir)
    tr = pipeline.read_transcript(pdir)
    return {
        "project": proj,
        "plan": plan,
        "transcript": tr.to_dict() if tr else None,
        "has_audio": next(iter(pdir.glob("audio.*")), None) is not None,
    }


def _pdir(pid: str) -> Path:
    try:
        pdir = pipeline.project_dir(pid)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    if not (pdir / "project.json").exists():
        raise HTTPException(404, "Proyecto no encontrado")
    return pdir


@app.post("/api/projects")
async def create_project(
    name: str = Form(""),
    audio: UploadFile | None = File(None),
    transcript: UploadFile | None = File(None),
    language: str = Form("auto"),
    whisper_model: str = Form(DEFAULT_WHISPER_MODEL),
    planner: str = Form("heuristic"),
):
    if audio is None and transcript is None:
        raise HTTPException(400, "Sube un audio o una transcripción (.json/.srt/.vtt).")
    if whisper_model not in WHISPER_MODELS:
        raise HTTPException(400, "Modelo de Whisper no válido")
    if planner not in ("heuristic", "llm"):
        raise HTTPException(400, "Planificador no válido")
    options = {"language": language, "whisper_model": whisper_model, "planner": planner}
    pid, pdir = pipeline.create_project(name, options)
    try:
        if audio is not None and audio.filename:
            ext = Path(audio.filename).suffix.lower()
            if ext not in AUDIO_EXT:
                raise HTTPException(400, f"Formato de audio no soportado: {ext}")
            with (pdir / f"audio{ext}").open("wb") as f:
                shutil.copyfileobj(audio.file, f)
        if transcript is not None and transcript.filename:
            ext = Path(transcript.filename).suffix.lower()
            if ext not in TRANSCRIPT_EXT:
                raise HTTPException(400, "La transcripción debe ser .json, .srt o .vtt")
            with (pdir / f"transcript_import{ext}").open("wb") as f:
                shutil.copyfileobj(transcript.file, f)
    except HTTPException:
        shutil.rmtree(pdir, ignore_errors=True)
        raise
    jid = _start_job("analyze", pid, pipeline.analyze, pdir)
    return {"project_id": pid, "job_id": jid}


@app.put("/api/projects/{pid}/plan")
def update_plan(pid: str, body: PlanUpdate):
    pdir = _pdir(pid)
    try:
        pipeline.apply_plan_edits(pdir, [e.model_dump(exclude_none=True) for e in body.scenes])
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return {"plan": pipeline.read_plan(pdir)}


@app.post("/api/projects/{pid}/render")
def render_project(pid: str, body: RenderRequest):
    pdir = _pdir(pid)
    if pipeline.read_plan(pdir) is None:
        raise HTTPException(409, "Primero analiza el proyecto.")
    if body.style not in STYLES:
        raise HTTPException(400, "Estilo no válido")
    jid = _start_job("render", pid, pipeline.render, pdir, body.model_dump())
    return {"job_id": jid}


@app.get("/api/jobs/{jid}")
def job(jid: str):
    with _jobs_lock:
        j = _jobs.get(jid)
        if not j:
            raise HTTPException(404, "Trabajo no encontrado")
        return dict(j)


@app.get("/api/projects/{pid}/files/{name}")
def project_file(pid: str, name: str):
    pdir = _pdir(pid)
    if "/" in name or "\\" in name or name.startswith("."):
        raise HTTPException(400, "Nombre no válido")
    if name.endswith(".mp4"):
        path = pdir / "output" / name
    else:
        path = next(iter(pdir.glob("audio.*")), None) if name == "audio" else None
    if path is None or not path.exists():
        raise HTTPException(404, "Archivo no encontrado")
    return FileResponse(path, filename=name if name.endswith(".mp4") else path.name)


@app.delete("/api/projects/{pid}")
def delete_project(pid: str):
    pdir = _pdir(pid)
    shutil.rmtree(pdir, ignore_errors=True)
    return {"ok": True}


app.mount("/", StaticFiles(directory=WEB_DIR, html=True), name="web")
