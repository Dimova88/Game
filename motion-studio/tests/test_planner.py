from studio.planner import (classify, make_scene, plan_heuristic, rebuild_scene, retime, Scene)
from studio.transcript import Word


def W(text, t0=0.0, d=0.4, gap=0.06):
    out, t = [], t0
    for w in text.split():
        out.append(Word(w, round(t, 3), round(t + d, 3)))
        t += d + gap
    return out


def test_classification_spanish_patterns():
    assert classify(W("El 45% de los usuarios abandona el video.")) == "stat"
    assert classify(W("¿Por qué el café despierta tu cerebro?")) == "question"
    assert classify(W("Necesitas café, agua y paciencia.")) == "bullets"
    assert classify(W("Python frente a JavaScript: cuál elegir.")) == "comparison"
    assert classify(W("En 2025 hubo grandes cambios.")) == "title"  # un año no es una cifra
    assert classify(W("Hoy, vamos a hablar de historia.")) == "title"  # coma sola no es lista


def test_bullets_skip_connectors_and_group_items():
    sc = make_scene(0, "bullets", W("Compré pan, leche y huevos."))
    groups = {}
    for t in sc.tokens:
        if t.role != "marker":
            groups.setdefault(t.group, []).append(t.text)
    assert list(groups.values()) == [["Compré", "pan,"], ["leche"], ["huevos."]]
    assert any(t.role == "marker" and t.text == "y" for t in sc.tokens)


def test_comparison_records_marker_time():
    words = W("Python frente a JavaScript cuál elegir", t0=10.0)
    sc = make_scene(0, "comparison", words)
    assert sc.meta["vs_start"] == words[1].start
    assert {t.group for t in sc.tokens if t.role == "word"} == {0, 1}


def test_invalid_kind_falls_back_to_title():
    sc = make_scene(0, "bullets", W("Hoy es martes."))  # una sola lista: no puede ser lista
    assert sc.kind == "title"
    sc2 = make_scene(0, "stat", W("Hoy es martes."))  # sin cifra
    assert sc2.kind == "title"


def test_auto_emphasis_picks_content_words():
    sc = make_scene(0, "title", W("La práctica constante vence a la motivación pasajera."))
    emph = [t.text for t in sc.tokens if t.emph]
    assert emph and all(len(e.strip(".")) >= 4 for e in emph)


def test_timeline_is_contiguous_and_covers_speech():
    words = W("Primera frase de prueba aquí. ¿Segunda pregunta? Tercera frase con 40% de datos. " 
              "Cuarta frase larga para comprobar el reparto de escenas.", t0=0.5, d=0.35, gap=0.1)
    duration = words[-1].end + 3
    scenes = plan_heuristic(words, duration)
    assert scenes[0].start == 0.0
    for a, b in zip(scenes, scenes[1:]):
        assert a.end == b.start, "no debe haber huecos entre escenas"
        assert a.start < a.end
    assert scenes[-1].end <= duration + 1e-6
    # Cada palabra se muestra dentro de la escena que la contiene
    for s in scenes:
        for t in s.tokens:
            assert s.start <= t.start <= s.end + 1e-6


def test_rebuild_keeps_timing_and_applies_emphasis():
    words = W("Estudiar de forma espaciada cambia el resultado final")
    sc = make_scene(0, "title", words)
    sc.start, sc.end = 0.0, 9.0
    new = rebuild_scene(sc, kind="title", emphasis_words=["resultado"])
    assert (new.start, new.end) == (0.0, 9.0)
    assert [t.text for t in new.tokens if t.emph] == ["resultado"]


def test_scene_roundtrip_serialization():
    sc = make_scene(3, "stat", W("Subió un 12% en mayo."))
    back = Scene.from_dict(sc.to_dict())
    assert back.kind == "stat" and back.id == 3
    assert [t.text for t in back.tokens if t.role == "value"] == ["12%"]


def test_retime_handles_empty_duration():
    scenes = [make_scene(0, "title", W("Hola a todos.", t0=2.0)), make_scene(1, "title", W("Adiós.", t0=6.0))]
    retime(scenes, None)
    assert scenes[0].start == 0.0 and scenes[0].end == scenes[1].start
