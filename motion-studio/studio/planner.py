"""Convierte la transcripción en escenas de motion graphics.

Cada frase se convierte en una escena. El tipo visual (title, stat, bullets, comparison,
question, quote) se decide por heurísticas del texto, o por un LLM opcional que solo
elige tipo y palabras a resaltar. Los TIEMPOS nunca los inventa el LLM: cada palabra
de la escena conserva el instante exacto en el que se pronuncia en el audio.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field

from .transcript import Word, normalize_word, split_sentences

KINDS = ("title", "stat", "bullets", "comparison", "question", "quote")

KIND_LABELS = {
    "title": "Texto cinético",
    "stat": "Cifra destacada",
    "bullets": "Lista animada",
    "comparison": "Comparación",
    "question": "Pregunta",
    "quote": "Cita",
}

STOPWORDS = set(
    """
    a al algo como con de del el ella ellos ellas en es esa ese eso esta este esto estos esas
    y o u e la las le les lo los me mi mis mas más muy no ni para pero por que qué quien
    se si sí sin sobre su sus te tu tus un una uno unos unas ya yo nos hay ha han fue ser son
    está están era eran sea pues también tambien cuando donde porque entre hasta desde
    the and or of to in on is are was be for with by at an it this that from as not but so
    we you they he she his her our your their can will just more than
    """.split()
)
CONJ = {"y", "e", "o", "u", "and", "or"}
# Expresiones que señalan una comparación entre dos lados.
COMPARE_PATTERNS = [("vs",), ("versus",), ("frente", "a"), ("comparado", "con"), ("mientras", "que"), ("en", "cambio"), ("a", "diferencia", "de")]

LEAD_IN = 0.25  # la escena empieza un poco antes de la primera palabra
MIN_SCENE_GAP = 0.5
TAIL = 2.0  # segundos que se mantiene la última escena tras su última palabra
MAX_SENTENCE_WORDS = 22


@dataclass
class Token:
    text: str
    start: float
    end: float
    role: str = "word"  # word | value (cifra) | marker (conector que no se muestra)
    group: int = 0  # elemento de lista / lado de comparación
    emph: bool = False

    @property
    def norm(self) -> str:
        return normalize_word(self.text)


@dataclass
class Scene:
    id: int
    kind: str
    start: float
    end: float
    sentence: str
    tokens: list[Token] = field(default_factory=list)
    meta: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["kind_label"] = KIND_LABELS.get(self.kind, self.kind)
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "Scene":
        return cls(
            id=d["id"],
            kind=d["kind"],
            start=float(d["start"]),
            end=float(d["end"]),
            sentence=d.get("sentence", ""),
            tokens=[Token(**t) for t in d.get("tokens", [])],
            meta=d.get("meta", {}),
        )


# ---------------------------------------------------------------- detección de patrones

def _value_score(text: str) -> int:
    if not re.search(r"\d", text):
        return 0
    if re.search(r"[%$€]", text) or re.search(r"\d[\d.,]*\s*(k|K|m|M|mil|millones|millón|%)\W*$", text):
        return 3
    if re.fullmatch(r"(19|20)\d{2}\W*", text):  # años sueltos no son "cifras" llamativas
        return 0
    return 2


def _value_index(words: list[Word]) -> int | None:
    best, best_i = 0, None
    for i, w in enumerate(words):
        s = _value_score(w.text)
        if s > best:
            best, best_i = s, i
    return best_i


def _comparison_marker(words: list[Word]) -> tuple[int, int] | None:
    norm = [normalize_word(w.text) for w in words]
    for i in range(1, len(words)):
        for pat in COMPARE_PATTERNS:
            n = len(pat)
            if tuple(norm[i : i + n]) == pat and i + n < len(words):
                return i, n
    return None


def _assign_groups(words: list[Word]) -> list[int]:
    """Asigna a cada palabra un índice de elemento de lista; -1 para conectores (y, o...)."""
    norm = [normalize_word(w.text) for w in words]
    assign = [0] * len(words)
    g = 0
    for i, w in enumerate(words):
        assign[i] = g
        if re.search(r"[,;]$", w.text.strip()) and i < len(words) - 1:
            g += 1
    comma_groups = g + 1
    if comma_groups >= 2:
        # El último elemento "A, B y C": el conector pasa a ser separador de elemento.
        last_start = min(i for i in range(len(words)) if assign[i] == g)
        conj = [i for i in range(last_start + 1, len(words)) if norm[i] in CONJ and i < len(words) - 1]
        if conj:
            k = conj[-1]
            for j in range(k, len(words)):
                assign[j] = g + 1 if j > k else -1
            assign[k] = -1
    # Conectores al inicio de un elemento se ocultan.
    for i in range(1, len(words)):
        if assign[i] >= 0 and assign[i] != assign[i - 1] and norm[i] in CONJ:
            assign[i] = -1
    # Renumera grupos a 0..n-1
    remap: dict[int, int] = {}
    for a in assign:
        if a >= 0 and a not in remap:
            remap[a] = len(remap)
    return [remap.get(a, -1) for a in assign]


def _auto_emphasis(words: list[Word]) -> set[int]:
    cands = []
    for i, w in enumerate(words):
        n = normalize_word(w.text)
        if len(n) >= 4 and n not in STOPWORDS and not re.search(r"\d", n):
            cands.append((-len(n), i))
    k = 1 if len(words) <= 5 else 2
    return {i for _, i in sorted(cands)[:k]}


def classify(words: list[Word]) -> str:
    """Tipo visual sugerido por heurística para una frase."""
    text = " ".join(w.text for w in words).strip()
    if text.endswith("?") or text.startswith("¿"):
        return "question"
    marker = _comparison_marker(words)
    if marker:
        return "comparison"
    vi = _value_index(words)
    if vi is not None and _value_score(words[vi].text) >= 2:
        return "stat"
    if len(set(a for a in _assign_groups(words) if a >= 0)) >= 3:
        return "bullets"
    return "title"


# ---------------------------------------------------------------- construcción de escenas

def make_scene(
    idx: int,
    kind: str,
    words: list[Word],
    emphasis_words: list[str] | None = None,
) -> Scene:
    """Crea una escena con el tipo pedido. Si el tipo no encaja con el texto, cae a 'title'."""
    if kind not in KINDS:
        kind = "title"
    n = len(words)
    roles = ["word"] * n
    groups = [0] * n
    meta: dict = {}

    if kind == "stat":
        vi = _value_index(words)
        if vi is None:
            kind = "title"
        else:
            roles[vi] = "value"
            meta["value"] = words[vi].text
    if kind == "bullets":
        groups = _assign_groups(words)
        if len({g for g in groups if g >= 0}) < 2:
            kind = "title"
            groups = [0] * n
        else:
            roles = ["marker" if g < 0 else "word" for g in groups]
            groups = [max(g, 0) for g in groups]
    if kind == "comparison":
        marker = _comparison_marker(words)
        if marker is None:
            kind = "title"
        else:
            mi, ml = marker
            for j in range(n):
                if mi <= j < mi + ml:
                    roles[j] = "marker"
                    groups[j] = 0
                else:
                    groups[j] = 0 if j < mi else 1
            meta["vs_start"] = words[mi].start
            meta["vs_word"] = " ".join(w.text for w in words[mi : mi + ml])

    # Palabras a resaltar
    if emphasis_words is not None:
        wanted = {normalize_word(e) for e in emphasis_words if normalize_word(e)}
        emph = {i for i, w in enumerate(words) if normalize_word(w.text) in wanted}
    elif kind == "title":
        emph = _auto_emphasis(words)
    else:
        emph = set()

    tokens = [
        Token(text=w.text, start=w.start, end=w.end, role=roles[i], group=groups[i], emph=i in emph)
        for i, w in enumerate(words)
    ]
    sentence = " ".join(w.text for w in words)
    start = words[0].start
    end = words[-1].end
    return Scene(id=idx, kind=kind, start=start, end=end, sentence=sentence, tokens=tokens, meta=meta)


def _merge_short(sentences: list[list[Word]]) -> list[list[Word]]:
    out: list[list[Word]] = []
    for s in sentences:
        if out and (len(s) < 3 or len(out[-1]) < 3) and len(out[-1]) + len(s) <= MAX_SENTENCE_WORDS:
            out[-1] = out[-1] + s
        else:
            out.append(s)
    return out


def _split_long(sentences: list[list[Word]]) -> list[list[Word]]:
    out: list[list[Word]] = []
    for s in sentences:
        if len(s) > MAX_SENTENCE_WORDS:
            mid = len(s) / 2
            commas = [i for i, w in enumerate(s) if re.search(r"[,;]$", w.text) and 4 <= i + 1 <= len(s) - 3]
            if commas:
                cut = min(commas, key=lambda i: abs(i + 1 - mid))
                out.append(s[: cut + 1])
                out.append(s[cut + 1 :])
                continue
        out.append(s)
    return out


def retime(scenes: list[Scene], duration: float | None = None) -> None:
    """Fija inicio/fin de cada escena a partir de sus palabras; escenas contiguas, sin huecos."""
    for i, s in enumerate(scenes):
        first = s.tokens[0].start if s.tokens else s.start
        start = max(0.0, first - LEAD_IN)
        if i > 0:
            start = max(start, scenes[i - 1].start + MIN_SCENE_GAP)
        s.start = 0.0 if i == 0 else round(start, 3)
    for i, s in enumerate(scenes):
        last_end = max((t.end for t in s.tokens), default=s.start)
        if i + 1 < len(scenes):
            s.end = scenes[i + 1].start
        else:
            s.end = last_end + TAIL
        if duration and duration > 0:
            s.end = min(s.end, duration)
        s.end = round(max(s.end, s.start + 0.5), 3)


def plan_heuristic(words: list[Word], duration: float | None = None) -> list[Scene]:
    sentences = _split_long(_merge_short(split_sentences(words)))
    scenes = [make_scene(i, classify(ws), ws) for i, ws in enumerate(sentences)]
    retime(scenes, duration)
    return scenes


def plan_with_llm(
    words: list[Word],
    duration: float | None,
    classifier,
) -> tuple[list[Scene], list[str]]:
    """`classifier(sentences_text) -> {idx: {"kind":..., "emphasis":[...]}}`. Devuelve escenas y avisos."""
    warnings: list[str] = []
    sentences = _split_long(_merge_short(split_sentences(words)))
    texts = [" ".join(w.text for w in ws) for ws in sentences]
    try:
        decisions = classifier(texts)
    except Exception as exc:  # el LLM es opcional: nunca debe romper el flujo
        warnings.append(f"LLM no disponible ({exc}); se usó la heurística.")
        decisions = {}
    scenes = []
    for i, ws in enumerate(sentences):
        d = decisions.get(i)
        if d:
            scenes.append(make_scene(i, d.get("kind", classify(ws)), ws, d.get("emphasis")))
        else:
            scenes.append(make_scene(i, classify(ws), ws))
    retime(scenes, duration)
    return scenes, warnings


def rebuild_scene(scene: Scene, kind: str | None = None, emphasis_words: list[str] | None = None) -> Scene:
    """Reconstruye una escena (p. ej. tras cambiar su tipo en la UI) conservando sus tiempos."""
    words = [Word(t.text, t.start, t.end) for t in scene.tokens]
    new = make_scene(scene.id, kind or scene.kind, words, emphasis_words)
    new.start, new.end = scene.start, scene.end
    return new
