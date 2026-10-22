"""Genera una transcripción de ejemplo con tiempos por palabra (para probar sin audio ni Whisper).

Uso:  python examples/make_demo_transcript.py > examples/demo_transcript.json
Los tiempos son sintéticos (~2.6 palabras/segundo con pausas en la puntuación).
"""

import json
import sys

SCRIPT = (
    "Tu cerebro consume el 20% de toda la energía de tu cuerpo. "
    "¿Por qué necesitamos tanta energía para pensar? "
    "La respuesta empieza en las neuronas, las células que transmiten señales. "
    "Cada neurona puede conectarse con miles de otras. "
    "Un café por la mañana, una caminata corta y un buen sueño mejoran la atención. "
    "Dormir menos de seis horas reduce la memoria de trabajo un 40%. "
    "Estudiar de forma espaciada frente a estudiar todo de golpe cambia el resultado. "
    "Esto es lo que debes recordar: la práctica constante vence a la motivación pasajera."
)


def build(script: str = SCRIPT, wps: float = 2.6) -> dict:
    words = []
    t = 0.4
    for raw in script.split():
        dur = max(0.18, min(0.9, 1.0 / wps * (0.6 + 0.05 * len(raw))))
        words.append({"text": raw, "start": round(t, 3), "end": round(t + dur, 3)})
        pause = 0.0
        if raw[-1] in ".?!":
            pause = 0.55
        elif raw[-1] in ",;":
            pause = 0.2
        t += dur + pause + 0.05
    return {"language": "es", "duration": round(t, 3), "source": "json", "words": words}


if __name__ == "__main__":
    json.dump(build(), sys.stdout, ensure_ascii=False, indent=1)
    sys.stdout.write("\n")
