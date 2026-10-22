import pytest

from studio.transcript import parse_json_transcript, parse_subtitles, split_sentences, Word


def test_json_words_are_sorted_and_cleaned():
    data = {"words": [
        {"text": "Hola", "start": 1.0, "end": 1.4},
        {"word": " mundo.", "start": 1.5, "end": 2.0},
        {"text": "  ", "start": 2.1, "end": 2.2},  # vacío: se descarta
        {"text": "bad", "start": "x"},  # tiempo inválido: se descarta
    ]}
    tr = parse_json_transcript(data)
    assert [w.text for w in tr.words] == ["Hola", "mundo."]
    assert tr.duration == 2.0
    assert tr.source == "json"


def test_segments_are_spread_over_time():
    tr = parse_json_transcript({"segments": [{"text": "uno dos tres", "start": 0.0, "end": 3.0}]})
    assert [round(w.start, 3) for w in tr.words] == [0.0, 0.9, 1.8]  # reparto proporcional a la longitud
    assert tr.source == "segments-approx"


def test_srt_is_parsed():
    srt = "1\n00:00:01,000 --> 00:00:03,000\nHola a todos\n\n2\n00:00:03,500 --> 00:00:05,000\n<i>Adiós</i>\n"
    tr = parse_subtitles(srt)
    assert tr.words[0].text == "Hola" and tr.words[0].start == 1.0
    assert tr.words[-1].text == "Adiós" and tr.words[-1].end == 5.0


def test_invalid_json_raises():
    with pytest.raises(ValueError):
        parse_json_transcript({"foo": 1})


def test_split_sentences_by_punctuation_and_pause():
    words = [Word("Uno.", 0, 0.4), Word("dos", 0.5, 0.8), Word("tres", 2.5, 2.9), Word("cuatro!", 3.0, 3.4)]
    sents = split_sentences(words, max_gap=0.9)
    assert [[w.text for w in s] for s in sents] == [["Uno."], ["dos"], ["tres", "cuatro!"]]
