"""Clasificador opcional con un LLM compatible con la API de OpenAI.

El LLM solo decide, por frase, el TIPO visual y las palabras a resaltar según el significado.
No reescribe el texto ni los tiempos, así que la sincronización con el audio no se pierde.
"""

from __future__ import annotations

import json
import urllib.request
from collections.abc import Callable

from .planner import KINDS

SYSTEM_PROMPT = """Eres director de motion graphics para vídeos de YouTube "faceless" (sin cara).
Recibes frases numeradas de una narración. Para cada frase elige el tipo de gráfico que mejor
la explica visualmente:
- "title": texto cinético con palabras clave (por defecto).
- "stat": la frase destaca una cifra, porcentaje o dato numérico importante.
- "bullets": enumeración de 2 o más elementos.
- "comparison": contraste entre dos cosas (A frente a B, antes/después...).
- "question": pregunta retórica o gancho.
- "quote": cita textual o frase de impacto.
Además devuelve hasta 2 "emphasis": palabras EXACTAS copiadas de la frase que merecen resaltarse.
Responde SOLO con JSON: {"scenes":[{"id": <número>, "kind": "<tipo>", "emphasis": ["..."]}]}"""


def make_llm_classifier(cfg: dict, timeout: float = 90.0) -> Callable[[list[str]], dict]:
    """Devuelve una función texts -> {idx: {"kind":..., "emphasis":[...]}} usando /chat/completions."""

    def classify(texts: list[str]) -> dict:
        out: dict[int, dict] = {}
        batch = 40
        for start in range(0, len(texts), batch):
            chunk = texts[start : start + batch]
            numbered = "\n".join(f"{start + i}. {t}" for i, t in enumerate(chunk))
            payload = {
                "model": cfg["model"],
                "temperature": 0.2,
                "response_format": {"type": "json_object"},
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": numbered},
                ],
            }
            headers = {"Content-Type": "application/json"}
            if cfg.get("api_key"):
                headers["Authorization"] = f"Bearer {cfg['api_key']}"
            req = urllib.request.Request(
                f"{cfg['base_url']}/chat/completions",
                data=json.dumps(payload).encode("utf-8"),
                headers=headers,
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                body = json.loads(resp.read().decode("utf-8"))
            content = body["choices"][0]["message"]["content"]
            data = json.loads(content)
            for item in data.get("scenes", []):
                try:
                    idx = int(item["id"])
                except (KeyError, TypeError, ValueError):
                    continue
                kind = item.get("kind")
                if kind not in KINDS:
                    continue
                emphasis = [e for e in item.get("emphasis", []) if isinstance(e, str)][:2]
                out[idx] = {"kind": kind, "emphasis": emphasis}
        return out

    return classify
