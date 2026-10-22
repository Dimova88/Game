"""Búsqueda de tipografías del sistema (con fallback a la fuente integrada de Pillow)."""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from PIL import ImageFont

from .config import FONTS_DIR

BOLD_NAMES = ("DejaVuSans-Bold.ttf", "Arial Bold.ttf", "arialbd.ttf", "Helvetica-Bold.ttf",
              "Montserrat-Bold.ttf", "Roboto-Bold.ttf", "Inter-Bold.ttf", "LiberationSans-Bold.ttf")
REGULAR_NAMES = ("DejaVuSans.ttf", "Arial.ttf", "arial.ttf", "Helvetica.ttc", "Roboto-Regular.ttf",
                 "Inter-Regular.ttf", "LiberationSans-Regular.ttf")
SEARCH_DIRS = [
    FONTS_DIR,
    Path("/usr/share/fonts"),
    Path("/usr/local/share/fonts"),
    Path.home() / ".fonts",
    Path.home() / ".local/share/fonts",
    Path("C:/Windows/Fonts"),
    Path("/System/Library/Fonts"),
    Path("/System/Library/Fonts/Supplemental"),
    Path("/Library/Fonts"),
    Path.home() / "Library/Fonts",
]


@lru_cache(maxsize=None)
def _find(bold: bool) -> str | None:
    env = os.environ.get("MOTION_FONT_BOLD" if bold else "MOTION_FONT_REGULAR")
    if env and Path(env).exists():
        return env
    names = {n.lower() for n in (BOLD_NAMES if bold else REGULAR_NAMES)}
    for d in SEARCH_DIRS:
        if not d.exists():
            continue
        for root, _dirs, files in os.walk(d):
            for f in files:
                if f.lower() in names:
                    return str(Path(root) / f)
    return None


@lru_cache(maxsize=512)
def get_font(bold: bool, size: int) -> ImageFont.FreeTypeFont:
    size = max(8, int(size))
    path = _find(bold)
    if path:
        return ImageFont.truetype(path, size)
    return ImageFont.load_default(size=size)  # Pillow >= 10.1 incluye una fuente escalable


def font_info() -> dict:
    return {"bold": _find(True), "regular": _find(False)}
