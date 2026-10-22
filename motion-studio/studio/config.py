"""Rutas y configuración global (todas sobrescribibles con variables de entorno)."""

from __future__ import annotations

import os
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PROJECTS_DIR = Path(os.environ.get("MOTION_PROJECTS_DIR", ROOT / "projects"))
WEB_DIR = ROOT / "web"
FONTS_DIR = ROOT / "fonts"  # coloca aquí .ttf propios si quieres fijar tipografías

WHISPER_MODELS = ["tiny", "base", "small", "medium", "large-v3"]
DEFAULT_WHISPER_MODEL = os.environ.get("MOTION_WHISPER_MODEL", "small")

LANGUAGES = {
    "auto": "Detectar automáticamente",
    "es": "Español",
    "en": "Inglés",
    "pt": "Portugués",
    "fr": "Francés",
    "de": "Alemán",
    "it": "Italiano",
}

# Formato de salida: relación de aspecto -> (ancho, alto) relativos a la resolución "corta".
ASPECTS = {
    "16:9": (16, 9),  # YouTube horizontal
    "9:16": (9, 16),  # Shorts / vertical
    "1:1": (1, 1),
}
RESOLUTIONS = {"720p": 720, "1080p": 1080}


def ffmpeg_path() -> str:
    """Devuelve el binario de ffmpeg: FFMPEG_BIN > ffmpeg bundled (imageio-ffmpeg) > PATH."""
    env = os.environ.get("FFMPEG_BIN")
    if env:
        return env
    try:
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:  # pragma: no cover - depende del entorno
        return shutil.which("ffmpeg") or "ffmpeg"


def llm_settings() -> dict | None:
    """Configuración opcional de un LLM compatible con OpenAI (p. ej. OpenAI, Ollama, LM Studio)."""
    base = os.environ.get("MOTION_LLM_BASE_URL")
    model = os.environ.get("MOTION_LLM_MODEL")
    if not base or not model:
        return None
    return {
        "base_url": base.rstrip("/"),
        "model": model,
        "api_key": os.environ.get("MOTION_LLM_API_KEY", ""),
    }
