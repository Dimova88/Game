"""Orquesta los dos pasos de un proyecto:

1. analyze: audio (o transcripción importada) -> transcript.json + plan.json (escenas)
2. render:  plan + estilo + formato -> output/<nombre>.mp4

Separar ambos pasos permite revisar/editar el plan y cambiar de estilo sin volver a transcribir.
"""

from __future__ import annotations

import json
import re
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from .config import ASPECTS, LANGUAGES, PROJECTS_DIR, RESOLUTIONS, llm_settings
from .llm import make_llm_classifier
from .media import probe_duration
from .planner import Scene, plan_heuristic, plan_with_llm, rebuild_scene, retime
from .renderer import Renderer
from .styles import get_style
from .transcribe import transcribe_audio
from .transcript import Transcript, load_transcript_file

Progress = Callable[[str, float], None]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def project_dir(pid: str) -> Path:
    if not re.fullmatch(r"[a-f0-9]{12}", pid):
        raise ValueError("ID de proyecto inválido")
    return PROJECTS_DIR / pid


def load_project(pdir: Path) -> dict:
    return json.loads((pdir / "project.json").read_text(encoding="utf-8"))


def save_project(pdir: Path, data: dict) -> None:
    pdir.mkdir(parents=True, exist_ok=True)
    (pdir / "project.json").write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def create_project(name: str, options: dict) -> tuple[str, Path]:
    pid = uuid.uuid4().hex[:12]
    pdir = PROJECTS_DIR / pid
    pdir.mkdir(parents=True, exist_ok=True)
    save_project(
        pdir,
        {
            "id": pid,
            "name": name or "Proyecto sin nombre",
            "created": _now(),
            "updated": _now(),
            "options": options,
            "audio": None,
            "duration": 0.0,
            "transcript_source": None,
            "status": "created",
            "warnings": [],
            "outputs": [],
            "error": None,
        },
    )
    return pid, pdir


def read_plan(pdir: Path) -> dict | None:
    p = pdir / "plan.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def read_transcript(pdir: Path) -> Transcript | None:
    p = pdir / "transcript.json"
    return Transcript.from_dict(json.loads(p.read_text(encoding="utf-8"))) if p.exists() else None


def analyze(pdir: Path, progress: Progress | None = None) -> None:
    """Transcribe (o lee la transcripción importada) y genera el plan de escenas."""
    proj = load_project(pdir)
    opts = proj["options"]
    prog = progress or (lambda stage, p: None)
    warnings: list[str] = []
    audio = next(iter(sorted(pdir.glob("audio.*"))), None)
    imported = next(iter(sorted(pdir.glob("transcript_import.*"))), None)

    duration = probe_duration(audio) if audio else None
    if imported:
        prog("Leyendo transcripción importada", 0.1)
        transcript = load_transcript_file(imported)
        proj["transcript_source"] = transcript.source
        if transcript.source.endswith("approx"):
            warnings.append("La transcripción importada no tiene tiempos por palabra: la sincronía es aproximada.")
    else:
        if not audio:
            raise ValueError("El proyecto no tiene audio ni transcripción.")
        prog("Transcribiendo audio con Whisper", 0.02)
        model = opts.get("whisper_model", "small")
        transcript = transcribe_audio(
            audio,
            model_name=model,
            language=opts.get("language", "auto"),
            progress=lambda p: prog("Transcribiendo audio con Whisper", 0.02 + 0.6 * p),
        )
        proj["transcript_source"] = f"whisper:{model}"
    if not transcript.words:
        raise ValueError("No se detectó voz en el audio.")
    if duration is None:
        duration = transcript.duration

    (pdir / "transcript.json").write_text(json.dumps(transcript.to_dict(), ensure_ascii=False, indent=1), encoding="utf-8")

    prog("Creando escenas de motion graphics", 0.75)
    planner = opts.get("planner", "heuristic")
    cfg = llm_settings()
    if planner == "llm" and cfg:
        prog("Clasificando frases con el LLM", 0.8)
        scenes, w = plan_with_llm(transcript.words, duration, make_llm_classifier(cfg))
        warnings.extend(w)
        planner_used = f"llm:{cfg['model']}"
    else:
        if planner == "llm":
            warnings.append("LLM no configurado (MOTION_LLM_BASE_URL / MOTION_LLM_MODEL); se usó la heurística.")
        scenes = plan_heuristic(transcript.words, duration)
        planner_used = "heuristic"

    plan = {"planner": planner_used, "scenes": [s.to_dict() for s in scenes]}
    (pdir / "plan.json").write_text(json.dumps(plan, ensure_ascii=False, indent=1), encoding="utf-8")

    proj.update(
        {
            "duration": round(float(duration or transcript.duration), 3),
            "status": "analyzed",
            "warnings": warnings,
            "error": None,
            "updated": _now(),
            "word_count": len(transcript.words),
            "scene_count": len(scenes),
        }
    )
    save_project(pdir, proj)
    prog("Análisis completado", 1.0)


def apply_plan_edits(pdir: Path, edits: list[dict]) -> None:
    """Aplica cambios del usuario: tipo de escena y palabras a resaltar (los tiempos no cambian)."""
    plan = read_plan(pdir)
    if plan is None:
        raise ValueError("Primero hay que analizar el proyecto.")
    scenes = [Scene.from_dict(s) for s in plan["scenes"]]
    out = []
    for sc in scenes:
        e = next((x for x in edits if int(x.get("id", -1)) == sc.id), None)
        if e:
            kind = e.get("kind", sc.kind)
            emph = e.get("emphasis")
            if emph is not None:
                emph = [x for x in emph if isinstance(x, str)]
            sc = rebuild_scene(sc, kind=kind, emphasis_words=emph)
        out.append(sc)
    retime(out, load_project(pdir).get("duration"))  # mantiene escenas contiguas tras el cambio
    plan["scenes"] = [s.to_dict() for s in out]
    (pdir / "plan.json").write_text(json.dumps(plan, ensure_ascii=False, indent=1), encoding="utf-8")


def render(pdir: Path, render_opts: dict, progress: Progress | None = None) -> str:
    """Renderiza el vídeo y devuelve el nombre del archivo generado dentro de output/."""
    prog = progress or (lambda stage, p: None)
    proj = load_project(pdir)
    plan = read_plan(pdir)
    transcript = read_transcript(pdir)
    if plan is None or transcript is None:
        raise ValueError("Primero hay que analizar el proyecto.")

    style = get_style(render_opts.get("style", "neon_tech"))
    aspect = render_opts.get("aspect", "16:9")
    res = render_opts.get("resolution", "1080p")
    fps = int(render_opts.get("fps", 30))
    captions = bool(render_opts.get("captions", True))
    if aspect not in ASPECTS:
        raise ValueError(f"Formato no soportado: {aspect}")
    if res not in RESOLUTIONS:
        raise ValueError(f"Resolución no soportada: {res}")
    if fps not in (24, 25, 30, 60):
        raise ValueError("FPS no soportados (24, 25, 30 o 60).")
    aw, ah = ASPECTS[aspect]
    short = RESOLUTIONS[res]
    if aw >= ah:
        W, H = round(short * aw / ah / 2) * 2, short
    else:
        W, H = short, round(short * ah / aw / 2) * 2

    scenes = [Scene.from_dict(s) for s in plan["scenes"]]
    audio = next(iter(sorted(pdir.glob("audio.*"))), None)
    duration = float(proj.get("duration") or transcript.duration)

    renderer = Renderer(style, W, H, fps, scenes, transcript.words, duration, captions=captions)
    out_dir = pdir / "output"
    out_dir.mkdir(exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    name = f"{style.key}_{aspect.replace(':', 'x')}_{res}_{stamp}.mp4"
    prog("Renderizando frames", 0.02)
    renderer.render_video(
        out_dir / name,
        audio_path=audio,
        progress=lambda p: prog("Renderizando frames", 0.02 + 0.96 * p),
    )
    proj["outputs"].append(
        {
            "file": name,
            "style": style.key,
            "style_name": style.name,
            "aspect": aspect,
            "resolution": f"{W}x{H}",
            "fps": fps,
            "captions": captions,
            "created": _now(),
        }
    )
    proj["status"] = "rendered"
    proj["updated"] = _now()
    save_project(pdir, proj)
    prog("Vídeo listo", 1.0)
    return name


def list_projects() -> list[dict]:
    if not PROJECTS_DIR.exists():
        return []
    items = []
    for p in PROJECTS_DIR.iterdir():
        if (p / "project.json").exists():
            try:
                items.append(load_project(p))
            except (OSError, ValueError):
                continue
    return sorted(items, key=lambda x: x.get("updated", ""), reverse=True)


__all__ = ["analyze", "render", "apply_plan_edits", "create_project", "project_dir", "load_project",
           "list_projects", "read_plan", "read_transcript", "LANGUAGES"]
