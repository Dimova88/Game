"""Utilidades de media basadas en ffmpeg (sin ffprobe: la duración se lee de la salida de ffmpeg)."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

from .config import ffmpeg_path

_DURATION_RE = re.compile(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)")


def probe_duration(path: str | Path) -> float | None:
    """Duración en segundos de un archivo de audio/vídeo, o None si no se puede leer."""
    proc = subprocess.run(
        [ffmpeg_path(), "-hide_banner", "-i", str(path)],
        capture_output=True,
        text=True,
        errors="replace",
    )
    m = _DURATION_RE.search(proc.stderr or "")
    if not m:
        return None
    h, mi, s = int(m.group(1)), int(m.group(2)), float(m.group(3))
    return h * 3600 + mi * 60 + s


def has_audio_stream(path: str | Path) -> bool:
    proc = subprocess.run(
        [ffmpeg_path(), "-hide_banner", "-i", str(path)],
        capture_output=True,
        text=True,
        errors="replace",
    )
    return "Audio:" in (proc.stderr or "")
