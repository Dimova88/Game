"""Transcripción local con faster-whisper y tiempos por palabra (word_timestamps)."""

from __future__ import annotations

import threading
from collections.abc import Callable
from pathlib import Path

from .transcript import Transcript, Word

_models: dict[str, object] = {}
_lock = threading.Lock()


def _device() -> tuple[str, str]:
    """(device, compute_type): CUDA si hay GPU disponible, si no CPU con int8 (rápido y ligero)."""
    try:
        import ctranslate2

        if ctranslate2.get_cuda_device_count() > 0:
            return "cuda", "float16"
    except Exception:
        pass
    return "cpu", "int8"


def _get_model(name: str):
    with _lock:
        if name not in _models:
            from faster_whisper import WhisperModel

            device, compute = _device()
            _models[name] = WhisperModel(name, device=device, compute_type=compute)
        return _models[name]


def transcribe_audio(
    audio_path: str | Path,
    model_name: str = "small",
    language: str | None = None,
    progress: Callable[[float], None] | None = None,
) -> Transcript:
    """Transcribe el audio y devuelve cada palabra con su inicio y fin en segundos.

    La primera ejecución descarga el modelo desde Hugging Face (requiere internet una vez).
    """
    model = _get_model(model_name)
    segments, info = model.transcribe(
        str(audio_path),
        language=None if not language or language == "auto" else language,
        word_timestamps=True,
        vad_filter=True,
        beam_size=5,
    )
    total = float(info.duration or 0) or 1.0
    words: list[Word] = []
    for seg in segments:  # generador: se consume progresivamente
        if progress:
            progress(min(1.0, seg.end / total))
        for w in seg.words or []:
            text = (w.word or "").strip()
            if text:
                words.append(Word(text, round(float(w.start), 3), round(float(w.end), 3)))
    return Transcript(
        words=words,
        language=info.language,
        duration=float(info.duration or (words[-1].end if words else 0.0)),
        source="whisper",
        model=model_name,
    )
