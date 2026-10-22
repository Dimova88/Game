"""Modelo de transcripción con tiempos por palabra + lectores de transcripciones externas."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

SENTENCE_END_RE = re.compile(r"[.!?…]+[\"'»)\]]*$")
_TS_RE = re.compile(r"(?:(\d+):)?(\d{1,2}):(\d{2})[,.](\d{1,3})")


@dataclass
class Word:
    text: str
    start: float
    end: float

    def to_dict(self) -> dict:
        return {"text": self.text, "start": round(self.start, 3), "end": round(self.end, 3)}


@dataclass
class Transcript:
    words: list[Word] = field(default_factory=list)
    language: str | None = None
    duration: float = 0.0
    source: str = "whisper"  # whisper | json | subtitles | subtitles-approx | segments-approx
    model: str | None = None

    def to_dict(self) -> dict:
        return {
            "language": self.language,
            "duration": round(self.duration, 3),
            "source": self.source,
            "model": self.model,
            "words": [w.to_dict() for w in self.words],
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Transcript":
        return cls(
            words=[Word(w["text"], float(w["start"]), float(w["end"])) for w in data.get("words", [])],
            language=data.get("language"),
            duration=float(data.get("duration") or 0.0),
            source=data.get("source", "json"),
            model=data.get("model"),
        )

    def text(self) -> str:
        return " ".join(w.text for w in self.words)


def normalize_word(text: str) -> str:
    """Minúsculas sin puntuación (conserva letras con acento, dígitos, % y monedas)."""
    return re.sub(r"[^\w%$€]", "", text.lower())


def split_sentences(words: list[Word], max_gap: float = 0.9) -> list[list[Word]]:
    """Parte la lista de palabras en frases: por puntuación final o por pausas largas."""
    sentences: list[list[Word]] = []
    current: list[Word] = []
    for i, w in enumerate(words):
        current.append(w)
        is_end = bool(SENTENCE_END_RE.search(w.text.strip()))
        gap = (words[i + 1].start - w.end) if i + 1 < len(words) else 0.0
        if is_end or gap > max_gap:
            sentences.append(current)
            current = []
    if current:
        sentences.append(current)
    return sentences


def _clean_words(raw: list[dict]) -> list[Word]:
    out: list[Word] = []
    for item in raw:
        text = str(item.get("text", item.get("word", ""))).strip()
        if not text:
            continue
        try:
            start = float(item["start"])
            end = float(item.get("end", start + 0.3))
        except (KeyError, TypeError, ValueError):
            continue
        out.append(Word(text, start, max(end, start + 0.01)))
    out.sort(key=lambda w: w.start)
    return out


def _spread(text: str, start: float, end: float) -> list[Word]:
    """Reparte el tiempo de un bloque entre sus palabras proporcionalmente a su longitud."""
    parts = text.split()
    if not parts or end <= start:
        return []
    total = sum(len(p) for p in parts)
    cursor = start
    out = []
    for p in parts:
        span = (end - start) * len(p) / total
        out.append(Word(p, cursor, cursor + span))
        cursor += span
    return out


def parse_json_transcript(data) -> Transcript:
    """Acepta {"words":[{text|word,start,end}]}, {"segments":[{text,start,end}]} o una lista de palabras."""
    if isinstance(data, list):
        words = _clean_words(data)
        source = "json"
    elif isinstance(data, dict) and "words" in data:
        words = _clean_words(data["words"])
        source = "json"
    elif isinstance(data, dict) and "segments" in data:
        words = []
        for seg in data["segments"]:
            words.extend(_spread(str(seg.get("text", "")), float(seg["start"]), float(seg["end"])))
        source = "segments-approx"
    else:
        raise ValueError("JSON no reconocido: se esperaba 'words' o 'segments' con tiempos.")
    if not words:
        raise ValueError("La transcripción no contiene palabras con tiempos.")
    return Transcript(
        words=words,
        language=data.get("language") if isinstance(data, dict) else None,
        duration=max(w.end for w in words),
        source=source,
    )


def _ts(value: str) -> float:
    m = _TS_RE.fullmatch(value.strip())
    if not m:
        raise ValueError(f"Marca de tiempo inválida: {value!r}")
    h = int(m.group(1) or 0)
    frac = m.group(4).ljust(3, "0")
    return h * 3600 + int(m.group(2)) * 60 + int(m.group(3)) + int(frac) / 1000


def parse_subtitles(text: str) -> Transcript:
    """Lee SRT/VTT. Como no hay tiempos por palabra, se reparten dentro de cada bloque (aproximado)."""
    words: list[Word] = []
    blocks = re.split(r"\n\s*\n", text.replace("\r\n", "\n"))
    for block in blocks:
        lines = [ln for ln in block.split("\n") if ln.strip()]
        for i, ln in enumerate(lines):
            if "-->" in ln:
                left, right = ln.split("-->", 1)
                start = _ts(left)
                end = _ts(right.split()[0])
                body = " ".join(lines[i + 1 :])
                body = re.sub(r"<[^>]+>", "", body)  # etiquetas VTT/SRT
                words.extend(_spread(body, start, end))
                break
    if not words:
        raise ValueError("No se encontraron bloques de subtítulos con tiempos.")
    return Transcript(words=words, duration=max(w.end for w in words), source="subtitles-approx")


def load_transcript_file(path: str | Path) -> Transcript:
    path = Path(path)
    suffix = path.suffix.lower()
    raw = path.read_text(encoding="utf-8-sig")
    if suffix == ".json":
        return parse_json_transcript(json.loads(raw))
    if suffix in (".srt", ".vtt"):
        return parse_subtitles(raw)
    raise ValueError("Formato de transcripción no soportado (usa .json, .srt o .vtt).")
