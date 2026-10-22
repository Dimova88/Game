import json
import subprocess
from pathlib import Path

import pytest

from studio.config import ffmpeg_path
from studio.media import probe_duration
from studio.planner import plan_heuristic
from studio.renderer import Renderer, caption_chunks
from studio.styles import STYLES, get_style
from studio.transcript import Transcript

EXAMPLE = Path(__file__).resolve().parent.parent / "examples" / "demo_transcript.json"


@pytest.fixture(scope="module")
def demo():
    tr = Transcript.from_dict(json.loads(EXAMPLE.read_text(encoding="utf-8")))
    return tr, plan_heuristic(tr.words, tr.duration)


@pytest.mark.parametrize("key", list(STYLES))
def test_frames_render_for_every_style(demo, key):
    tr, scenes = demo
    r = Renderer(get_style(key), 640, 360, 30, scenes, tr.words, tr.duration)
    for s in scenes:
        f = r.frame(s.start + min(1.2, (s.end - s.start) / 2))
        assert f.size == (640, 360)
    img = r.frame(scenes[0].start + 1.0).convert("RGB")
    # debe haber contraste (texto dibujado sobre el fondo)
    lo, hi = img.convert("L").getextrema()
    assert hi - lo > 40


def test_vertical_format_and_no_captions(demo):
    tr, scenes = demo
    r = Renderer(get_style("bold_pop"), 360, 640, 24, scenes, tr.words, tr.duration, captions=False)
    assert r.frame(1.0).size == (360, 640)
    assert r._caption_layer(1.0) is None


def test_caption_chunks_respect_limits(demo):
    tr, _ = demo
    chunks = caption_chunks(tr.words)
    assert chunks and all(1 <= len(c["words"]) <= 5 for c in chunks)
    assert chunks[0]["start"] == tr.words[0].start


def test_render_mp4_with_audio(tmp_path, demo):
    tr, scenes = demo
    audio = tmp_path / "tone.wav"
    subprocess.run([ffmpeg_path(), "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i",
                    f"sine=frequency=440:duration={tr.duration:.2f}", "-ac", "1", str(audio)], check=True)
    out = tmp_path / "out.mp4"
    dur = probe_duration(audio)
    r = Renderer(get_style(get_style("corporate_clean").key), 320, 180, 24, scenes[:3], tr.words[:20], min(dur, scenes[2].end))
    msgs = []
    r.render_video(out, audio_path=audio, progress=msgs.append)
    assert out.exists() and out.stat().st_size > 1000
    assert msgs and msgs[-1] == 1.0
    assert abs(probe_duration(out) - min(dur, scenes[2].end)) < 0.3
