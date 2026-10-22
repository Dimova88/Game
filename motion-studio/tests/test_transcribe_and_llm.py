import json
from types import SimpleNamespace

from studio import transcribe as tmod
from studio.llm import make_llm_classifier
from studio.planner import plan_with_llm
from studio.transcript import Word


class FakeModel:
    def transcribe(self, path, **kwargs):
        assert kwargs["word_timestamps"] is True
        words = [SimpleNamespace(word=" Hola", start=0.5, end=0.9), SimpleNamespace(word=" mundo.", start=1.0, end=1.6)]
        seg = SimpleNamespace(end=1.6, words=words)
        info = SimpleNamespace(duration=2.0, language="es")
        return iter([seg]), info


def test_transcribe_adapter_uses_word_timestamps(monkeypatch):
    monkeypatch.setitem(tmod._models, "tiny", FakeModel())
    tr = tmod.transcribe_audio("x.wav", "tiny", "es")
    assert [w.text for w in tr.words] == ["Hola", "mundo."]
    assert tr.words[0].start == 0.5 and tr.language == "es" and tr.source == "whisper"


def test_llm_classifier_parses_json(monkeypatch):
    body = {"choices": [{"message": {"content": json.dumps({"scenes": [
        {"id": 0, "kind": "stat", "emphasis": ["20%"]},
        {"id": 1, "kind": "inventado"},  # tipo inválido: se ignora
    ]})}}]}

    class Resp:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def read(self): return json.dumps(body).encode()

    monkeypatch.setattr("urllib.request.urlopen", lambda req, timeout=0: Resp())
    clf = make_llm_classifier({"base_url": "http://x/v1", "model": "m", "api_key": ""})
    out = clf(["Cerebro 20% de energía.", "Otra frase."])
    assert out == {0: {"kind": "stat", "emphasis": ["20%"]}}


def test_llm_failure_falls_back_to_heuristics():
    words = [Word("Compré", 0, 0.4), Word("pan,", 0.5, 0.9), Word("leche", 1.0, 1.4), Word("y", 1.5, 1.6), Word("huevos.", 1.7, 2.1)]

    def broken(_texts):
        raise RuntimeError("sin conexión")

    scenes, warnings = plan_with_llm(words, 5.0, broken)
    assert scenes and any("LLM no disponible" in w for w in warnings)
    assert scenes[0].kind == "bullets"
