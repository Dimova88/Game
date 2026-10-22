"""Motor de render: dibuja cada frame con Pillow y lo envía a ffmpeg (H.264 + audio original).

Todas las animaciones de texto se disparan con los tiempos reales de cada palabra, así que
el gráfico aparece exactamente cuando se pronuncia la palabra o frase correspondiente.
"""

from __future__ import annotations

import math
import random
import re
import subprocess
from bisect import bisect_right
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

from .config import ffmpeg_path
from .fonts import get_font
from .planner import Scene, Token
from .styles import Style
from .transcript import SENTENCE_END_RE, Word

WORD_ANIM = 0.38  # duración (s) de la entrada de cada palabra
TRANSITION = 0.5  # duración (s) de la transición entre escenas
RGB = tuple[int, int, int]


def _clamp(x: float, a: float = 0.0, b: float = 1.0) -> float:
    return a if x < a else b if x > b else x


def ease_out_cubic(p: float) -> float:
    p = _clamp(p)
    return 1 - (1 - p) ** 3


def ease_out_back(p: float) -> float:
    p = _clamp(p)
    c1 = 1.70158
    c3 = c1 + 1
    return 1 + c3 * (p - 1) ** 3 + c1 * (p - 1) ** 2


def _lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


def _mix(a: RGB, b: RGB, t: float) -> RGB:
    return tuple(int(round(_lerp(a[i], b[i], t))) for i in range(3))  # type: ignore[return-value]


@dataclass
class Block:
    """Texto ya maquetado: posición relativa de cada palabra dentro de un bloque."""

    font: object
    texts: list[str]
    pos: list[tuple[float, float]]
    width: int
    height: int
    lh: int
    widths: list[float] = field(default_factory=list)


def _wrap_widths(widths: list[float], space: float, max_w: float) -> list[list[int]]:
    lines: list[list[int]] = []
    cur: list[int] = []
    cw = 0.0
    for i, w in enumerate(widths):
        if not cur:
            cur, cw = [i], w
        elif cw + space + w <= max_w:
            cur.append(i)
            cw += space + w
        else:
            lines.append(cur)
            cur, cw = [i], w
    if cur:
        lines.append(cur)
    return lines


def caption_chunks(words: list[Word], max_words: int = 5, max_gap: float = 0.7) -> list[dict]:
    """Agrupa palabras en bloques de subtítulos (se rompe por puntuación, pausa o número de palabras)."""
    chunks: list[dict] = []
    cur: list[Word] = []
    for i, w in enumerate(words):
        cur.append(w)
        gap = (words[i + 1].start - w.end) if i + 1 < len(words) else 0.0
        if len(cur) >= max_words or SENTENCE_END_RE.search(w.text) or gap > max_gap or i == len(words) - 1:
            chunks.append({"start": cur[0].start, "end": cur[-1].end + 0.25, "words": cur})
            cur = []
    return chunks


class Renderer:
    def __init__(
        self,
        style: Style,
        width: int,
        height: int,
        fps: int,
        scenes: list[Scene],
        words: list[Word],
        duration: float,
        captions: bool = True,
    ):
        if not scenes:
            raise ValueError("No hay escenas que renderizar.")
        self.style = style
        self.W = width
        self.H = height
        self.fps = fps
        self.scenes = sorted(scenes, key=lambda s: s.start)
        self.starts = [s.start for s in self.scenes]
        self.duration = max(duration, self.scenes[-1].end)
        self.captions = captions
        self.m = min(width, height) / 1080.0  # escala de tipografía/espaciado
        self._bg = self._make_background()
        self._grid = self._make_grid() if "grid" in style.decor else None
        self._rng = random.Random(7)
        self._particles = [
            (self._rng.random(), self._rng.random(), self._rng.uniform(1.5, 4.5), self._rng.uniform(0.02, 0.09), self._rng.uniform(0, 6.28))
            for _ in range(34)
        ]
        self._chunks = caption_chunks(words) if captions else []
        self._chunk_starts = [c["start"] for c in self._chunks]
        self._text_cache: dict = {}
        self._block_cache: dict = {}

    # ------------------------------------------------------------ utilidades de dibujo
    def px(self, v: float) -> int:
        return int(round(v * self.m))

    def _disp(self, text: str) -> str:
        return text.upper() if self.style.uppercase else text

    def _text_img(self, text: str, size: int, bold: bool, color: RGB) -> Image.Image:
        key = (text, size, bold, color)
        img = self._text_cache.get(key)
        if img is not None:
            return img
        font = get_font(bold, size)
        l, t, r, b = font.getbbox(text)
        pad = max(4, size // 5)
        img = Image.new("RGBA", (r - l + 2 * pad, b - t + 2 * pad), (0, 0, 0, 0))
        ImageDraw.Draw(img).text((pad - l, pad - t), text, font=font, fill=(*color, 255))
        if len(self._text_cache) > 4000:
            self._text_cache.clear()
        self._text_cache[key] = img
        return img

    @staticmethod
    def _alpha(img: Image.Image, a: float) -> Image.Image:
        if a >= 0.999:
            return img
        if a <= 0.001:
            return Image.new("RGBA", img.size, (0, 0, 0, 0))
        lut = [int(v * a) for v in range(256)]
        out = img.copy()
        out.putalpha(img.getchannel("A").point(lut))
        return out

    @staticmethod
    def _composite(dst: Image.Image, src: Image.Image, x: float, y: float) -> None:
        x, y = int(round(x)), int(round(y))
        W, H = dst.size
        sx0, sy0 = max(0, -x), max(0, -y)
        dx0, dy0 = max(0, x), max(0, y)
        sw = min(src.width - sx0, W - dx0)
        sh = min(src.height - sy0, H - dy0)
        if sw <= 0 or sh <= 0:
            return
        crop = src if (sx0, sy0, sw, sh) == (0, 0, src.width, src.height) else src.crop((sx0, sy0, sx0 + sw, sy0 + sh))
        dst.alpha_composite(crop, (dx0, dy0))

    def _rounded(self, w: float, h: float, radius: float, color: tuple) -> Image.Image:
        w, h = max(1, int(w)), max(1, int(h))
        img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        ImageDraw.Draw(img).rounded_rectangle((0, 0, w - 1, h - 1), radius=max(0, int(radius)), fill=color)
        return img

    def _draw_word(
        self,
        layer: Image.Image,
        text: str,
        size: int,
        bold: bool,
        color: RGB,
        x: float,
        y: float,
        prog: float,
        motion: str,
        glow: bool = False,
    ) -> None:
        """Dibuja una palabra en (x, y) con la animación de entrada `motion` según progreso 0..1."""
        if prog <= 0:
            return
        e = ease_out_cubic(prog)
        dx = dy = 0.0
        scale = 1.0
        alpha = 1.0
        if motion == "slide_up":
            dy, alpha = (1 - e) * 60 * self.m, e
        elif motion == "pop":
            scale, alpha = 0.25 + 0.75 * ease_out_back(prog), min(1.0, prog * 1.8)
        elif motion == "fade":
            alpha = e
        elif motion == "slide_left":
            dx, alpha = -(1 - e) * 140 * self.m, e
        elif motion == "slide_right":
            dx, alpha = (1 - e) * 140 * self.m, e
        img = self._text_img(text, size, bold, color)
        if motion == "typewriter":
            n = max(1, math.ceil(len(text) * prog))
            if n < len(text):
                img = self._text_img(text[:n], size, bold, color)
        if scale != 1.0:
            w0, h0 = img.size
            img = img.resize((max(1, int(w0 * scale)), max(1, int(h0 * scale))), Image.BICUBIC)
            cx, cy = x + w0 / 2, y + h0 / 2
            x, y = cx - img.width / 2, cy - img.height / 2
        img = self._alpha(img, alpha)
        if glow and alpha > 0:
            mask = img.getchannel("A")
            halo = Image.new("RGBA", img.size, (*color, 0))
            halo.putalpha(mask)
            halo = halo.filter(ImageFilter.GaussianBlur(max(4, size // 6)))
            self._composite(layer, self._alpha(halo, 0.9), x + dx, y + dy)
        self._composite(layer, img, x + dx, y + dy)

    def _box(self, layer: Image.Image, x: float, y: float, w: float, h: float, color: tuple, alpha: float) -> None:
        pad = self.px(10)
        img = self._rounded(w + 2 * pad, h + pad, self.px(14), color)
        self._composite(layer, self._alpha(img, alpha), x - pad, y - pad * 0.5)

    # ------------------------------------------------------------ maquetado de texto
    def _fit(self, texts: list[str], max_w: float, max_h: float, base: float, bold: bool = True,
             lh_factor: float = 1.12, min_scale: float = 0.42) -> Block:
        """Busca el mayor tamaño de fuente en el que el texto cabe en max_w x max_h."""
        key = (tuple(texts), int(max_w), int(max_h), int(base), bold, lh_factor)
        if key in self._block_cache:
            return self._block_cache[key]
        size = max(10, int(base))
        floor = max(10, int(base * min_scale))
        while True:
            font = get_font(bold, size)
            space = font.getlength(" ")
            widths = [font.getlength(t) for t in texts]
            lines = _wrap_widths(widths, space, max_w)
            lh = int(size * lh_factor)
            h = len(lines) * lh
            if (max(widths, default=0) <= max_w and h <= max_h) or size <= floor:
                break
            size -= max(2, int(size * 0.05))
        block = self._layout_lines(texts, font, widths, space, lines, lh)
        self._block_cache[key] = block
        return block

    def _layout_lines(self, texts, font, widths, space, lines, lh) -> Block:
        line_w = [sum(widths[i] for i in ln) + space * (len(ln) - 1) for ln in lines]
        bw = max(line_w, default=0)
        pos: list[tuple[float, float]] = [(0.0, 0.0)] * len(texts)
        for li, ln in enumerate(lines):
            x = (bw - line_w[li]) / 2  # alineación centrada dentro del bloque
            for i in ln:
                pos[i] = (x, li * lh)
                x += widths[i] + space
        return Block(font=font, texts=texts, pos=pos, width=int(bw), height=len(lines) * lh, lh=lh, widths=widths)

    # ------------------------------------------------------------ fondo y decoración
    def _make_background(self) -> Image.Image:
        st = self.style
        small = Image.new("RGB", (48, 48))
        px = small.load()
        for y in range(48):
            for x in range(48):
                f = (x / 47) * 0.35 + (y / 47) * 0.65
                px[x, y] = _mix(st.bg_top, st.bg_bottom, f)
        return small.resize((self.W, self.H), Image.BICUBIC).convert("RGBA")

    def _make_grid(self) -> Image.Image:
        layer = Image.new("RGBA", (self.W, self.H), (0, 0, 0, 0))
        d = ImageDraw.Draw(layer)
        step = self.px(90)
        col = (*self.style.accent, 26)
        for x in range(0, self.W, step):
            d.line([(x, 0), (x, self.H)], fill=col, width=1)
        for y in range(0, self.H, step):
            d.line([(0, y), (self.W, y)], fill=col, width=1)
        return layer

    def _decor(self, t: float) -> Image.Image:
        st = self.style
        layer = Image.new("RGBA", (self.W, self.H), (0, 0, 0, 0))
        d = ImageDraw.Draw(layer)
        if self._grid is not None:
            layer.alpha_composite(self._grid)
            band_h = self.px(160)
            y = int((t * 90 * self.m) % (self.H + band_h)) - band_h
            grad = Image.new("RGBA", (self.W, band_h), (0, 0, 0, 0))
            gd = ImageDraw.Draw(grad)
            for r in range(band_h):  # banda luminosa que recorre la cuadrícula
                a = int(34 * (1 - abs(r - band_h / 2) / (band_h / 2)))
                gd.line([(0, r), (self.W, r)], fill=(*st.accent, a))
            self._composite(layer, grad, 0, y)
        if "particles" in st.decor:
            for i, (fx, fy, r, sp, ph) in enumerate(self._particles):
                x = fx * self.W + math.sin(t * 0.7 + ph) * 25 * self.m
                y = (fy * self.H - t * sp * self.H * 0.25) % self.H
                col = st.accent if i % 2 == 0 else st.accent2
                rr = r * self.m * 1.6
                d.ellipse((x - rr, y - rr, x + rr, y + rr), fill=(*col, 110))
        if "circles" in st.decor:
            cx = self.W * 0.9 + math.sin(t * 0.3) * 20 * self.m
            cy = self.H * 0.1
            rr = self.W * 0.2
            d.ellipse((cx - rr, cy - rr, cx + rr, cy + rr), fill=(*st.accent, 46))
            cx2, cy2, rr2 = self.W * 0.08, self.H * 0.92, self.W * 0.14
            d.ellipse((cx2 - rr2, cy2 - rr2, cx2 + rr2, cy2 + rr2), fill=(*st.accent2, 38))
        if "lines" in st.decor:
            sweep = 0.5 + 0.5 * math.sin(t * 0.8)
            w = self.W * (0.08 + 0.12 * sweep)
            y1 = self.H * 0.14
            d.rectangle((self.W * 0.08, y1, self.W * 0.08 + w, y1 + self.px(5)), fill=(*st.accent, 255))
            d.line([(self.W * 0.08, self.H * 0.86), (self.W * 0.92, self.H * 0.86)], fill=(*st.muted, 90), width=max(1, self.px(2)))
        return layer

    # ------------------------------------------------------------ escenas
    def _prog(self, lt: float, tok: Token, scene: Scene) -> float:
        return _clamp((lt - (tok.start - scene.start)) / WORD_ANIM)

    def _content_box(self, layout: str) -> tuple[float, float]:
        """(x0, max_w) del área de contenido (margen izquierdo y ancho útil)."""
        return self.W * 0.08, self.W * 0.84

    def _anchor_x(self, block: Block, x0: float, max_w: float) -> float:
        if self.style.layout == "left":
            return x0
        return x0 + (max_w - block.width) / 2

    def _draw_title(self, layer: Image.Image, scene: Scene, lt: float, cy_frac: float = 0.5, max_h_frac: float = 0.55) -> None:
        st = self.style
        texts = [self._disp(t.text) for t in scene.tokens]
        x0, max_w = self._content_box(st.layout)
        block = self._fit(texts, max_w, self.H * max_h_frac, self.px(120))
        ox = self._anchor_x(block, x0, max_w)
        oy = self.H * cy_frac - block.height / 2
        for i, tok in enumerate(scene.tokens):
            p = self._prog(lt, tok, scene)
            if p <= 0:
                continue
            bx, by = ox + block.pos[i][0], oy + block.pos[i][1]
            w = block.widths[i]
            color = st.text
            glow = False
            if tok.emph and st.emph_box:
                e = ease_out_cubic(p)
                self._box(layer, bx, by + self.px(4), w, block.lh * 0.98, st.accent, e)
                color = st.ink
            elif tok.emph:
                color = st.accent
                glow = st.glow
            self._draw_word(layer, texts[i], block.font.size, True, color, bx, by, p, st.entrance, glow=glow)

    def _draw_question(self, layer: Image.Image, scene: Scene, lt: float) -> None:
        st = self.style
        # Círculo con "?" que aparece al inicio de la escena
        p = _clamp(lt / 0.45)
        r = self.px(95)
        cx, cy = self.W / 2 if st.layout == "center" else self.W * 0.14, self.H * 0.25
        if p > 0:
            circ = self._rounded(2 * r, 2 * r, r, (*st.accent, 255))
            self._composite(layer, self._alpha(circ, min(1.0, ease_out_back(p))), cx - r, cy - r)
            qsize = int(r * 1.5)
            qw = get_font(True, qsize).getlength("?")
            self._draw_word(layer, "?", qsize, True, st.ink, cx - qw / 2, cy - r * 0.95, p, "fade")
        texts = [self._disp(t.text) for t in scene.tokens]
        x0, max_w = self._content_box(st.layout)
        block = self._fit(texts, max_w, self.H * 0.4, self.px(104))
        ox = self._anchor_x(block, x0, max_w)
        oy = self.H * 0.57 - block.height / 2
        for i, tok in enumerate(scene.tokens):
            pr = self._prog(lt, tok, scene)
            color = st.accent if "?" in tok.text or "¿" in tok.text else st.text
            self._draw_word(layer, texts[i], block.font.size, True, color, ox + block.pos[i][0], oy + block.pos[i][1], pr, st.entrance)

    def _draw_quote(self, layer: Image.Image, scene: Scene, lt: float) -> None:
        st = self.style
        p = _clamp(lt / 0.5)
        self._draw_word(layer, "\u201c", self.px(300), True, st.accent, self.W * 0.09, self.H * 0.14, p, "fade")
        texts = [self._disp(t.text) for t in scene.tokens]
        x0, max_w = self._content_box(st.layout)
        block = self._fit(texts, max_w, self.H * 0.5, self.px(96), bold=False)
        ox = self._anchor_x(block, x0, max_w)
        oy = self.H * 0.55 - block.height / 2
        for i, tok in enumerate(scene.tokens):
            pr = self._prog(lt, tok, scene)
            color = st.accent if tok.emph else st.text
            self._draw_word(layer, texts[i], block.font.size, False, color, ox + block.pos[i][0], oy + block.pos[i][1], pr, st.entrance)
        if scene.tokens:
            end_t = self._prog(lt, scene.tokens[-1], scene)
            w = block.width * ease_out_cubic(end_t)
            self._box(layer, ox, oy + block.height + self.px(18), w, self.px(6), st.accent, 1.0)

    def _draw_stat(self, layer: Image.Image, scene: Scene, lt: float) -> None:
        st = self.style
        val = next((t for t in scene.tokens if t.role == "value"), None)
        if val is None:
            return self._draw_title(layer, scene, lt)
        x0, max_w = self._content_box(st.layout)
        vblock = self._fit([val.text], max_w, self.H * 0.3, self.px(260))
        vx = self._anchor_x(vblock, x0, max_w)
        vy = self.H * 0.40 - vblock.height / 2
        vp = self._prog(lt, val, scene)
        self._draw_word(layer, val.text, vblock.font.size, True, st.accent, vx, vy, vp, "pop", glow=st.glow)

        # Barra de progreso para porcentajes
        m = re.search(r"(\d+(?:[.,]\d+)?)\s*%", val.text)
        if m:
            pct = min(100.0, float(m.group(1).replace(",", ".")))
            bp = ease_out_cubic(_clamp((lt - (val.start - scene.start) - 0.2) / 1.2))
            bw_full = max_w * 0.8 if st.layout == "center" else max_w * 0.7
            bx = x0 + (max_w - bw_full) / 2 if st.layout == "center" else x0
            by = self.H * 0.56
            bh = self.px(22)
            self._box(layer, bx, by, bw_full, bh, st.muted, 0.35 * bp)
            self._box(layer, bx, by, bw_full * pct / 100 * bp, bh, st.accent2 if st.accent2 else st.accent, 1.0)

        labels = [t for t in scene.tokens if t.role != "value"]
        if labels:
            texts = [self._disp(t.text) for t in labels]
            lblock = self._fit(texts, max_w * 0.9, self.H * 0.2, self.px(64), bold=False)
            lx = self._anchor_x(lblock, x0, max_w)
            ly = self.H * 0.66
            for i, tok in enumerate(labels):
                pr = self._prog(lt, tok, scene)
                color = st.accent if tok.emph else st.text
                self._draw_word(layer, texts[i], lblock.font.size, False, color, lx + lblock.pos[i][0], ly + lblock.pos[i][1], pr, st.entrance)

    def _groups(self, scene: Scene) -> dict[int, list[Token]]:
        groups: dict[int, list[Token]] = {}
        for t in scene.tokens:
            if t.role == "marker":
                continue
            groups.setdefault(t.group, []).append(t)
        return dict(sorted(groups.items()))

    def _draw_bullets(self, layer: Image.Image, scene: Scene, lt: float) -> None:
        st = self.style
        groups = self._groups(scene)
        if not groups:
            return
        item_w_total = self.W * 0.80 if st.layout == "center" else self.W * 0.84
        x_left = (self.W - item_w_total) / 2 if st.layout == "center" else self.W * 0.08
        badge = self.px(64)
        text_w = item_w_total - badge - self.px(70)
        # Tamaño común para todos los elementos
        base = self.px(78)
        size_block = None
        for size in range(base, self.px(40), -max(1, self.px(4))):
            font = get_font(True, size)
            space = font.getlength(" ")
            total_h = 0
            ok = True
            for toks in groups.values():
                texts = [self._disp(t.text) for t in toks]
                widths = [font.getlength(t) for t in texts]
                lines = _wrap_widths(widths, space, text_w)
                total_h += len(lines) * int(size * 1.12) + self.px(44)
                if max(widths, default=0) > text_w:
                    ok = False
            if ok and total_h <= self.H * 0.56:
                size_block = size
                break
        size = size_block or self.px(40)
        font = get_font(True, size)
        space = font.getlength(" ")
        lh = int(size * 1.12)
        y = self.H * 0.5 - self._bullets_height(groups, font, space, text_w, lh) / 2
        for gi, toks in enumerate(groups.values()):
            texts = [self._disp(t.text) for t in toks]
            widths = [font.getlength(t) for t in texts]
            lines = _wrap_widths(widths, space, text_w)
            block_h = len(lines) * lh
            p = _clamp((lt - (toks[0].start - scene.start)) / 0.45)
            e = ease_out_cubic(p)
            dx = -(1 - e) * 140 * self.m
            if p > 0:
                if st.cards:
                    card = self._rounded(item_w_total, block_h + self.px(44), self.px(26), st.card_color)
                    self._composite(layer, self._alpha(card, e), x_left + dx, y - self.px(15))
                # indicador numerado
                circ = self._rounded(badge, badge, badge / 2, (*st.accent, 255))
                self._composite(layer, self._alpha(circ, e), x_left + dx + self.px(14), y + block_h / 2 - badge / 2)
                num = str(gi + 1)
                nimg = self._text_img(num, int(badge * 0.5), True, st.ink)
                self._composite(layer, self._alpha(nimg, e), x_left + dx + self.px(14) + badge / 2 - nimg.width / 2 + self.px(2), y + block_h / 2 - nimg.height / 2)
            tx0 = x_left + badge + self.px(44)
            for li, ln in enumerate(lines):
                x = tx0
                lw = sum(widths[i] for i in ln) + space * (len(ln) - 1)
                if st.layout == "center":
                    x = tx0 + (text_w - lw) / 2
                for i in ln:
                    tok = toks[i]
                    color = st.accent if tok.emph else st.text
                    self._draw_word(layer, texts[i], size, True, color, x + dx, y + li * lh, p, "fade")
                    x += widths[i] + space
            y += block_h + self.px(44)

    def _bullets_height(self, groups, font, space, text_w, lh) -> float:
        h = 0.0
        for toks in groups.values():
            texts = [self._disp(t.text) for t in toks]
            widths = [font.getlength(t) for t in texts]
            h += len(_wrap_widths(widths, space, text_w)) * lh + self.px(44)
        return h - self.px(44)

    def _draw_comparison(self, layer: Image.Image, scene: Scene, lt: float) -> None:
        st = self.style
        groups = self._groups(scene)
        sides = [groups.get(0, []), groups.get(1, [])]
        if len(sides) < 2 or not sides[1]:
            return self._draw_title(layer, scene, lt)
        card_w = self.W * 0.42
        card_h = self.H * 0.42
        cy = self.H * 0.5 - card_h / 2
        lefts = [self.W * 0.05, self.W * 0.53]
        colors = [st.accent, st.accent2]
        for si, toks in enumerate(sides):
            first = toks[0]
            p_card = _clamp((lt - (first.start - scene.start)) / 0.5)
            e = ease_out_cubic(p_card)
            dx = (-1 if si == 0 else 1) * (1 - e) * self.W * 0.25
            cx0 = lefts[si] + dx
            if st.cards:
                card = self._rounded(card_w, card_h, self.px(30), st.card_color)
                self._composite(layer, self._alpha(card, e), cx0, cy)
            self._box(layer, cx0 + self.px(30), cy + self.px(24), card_w - self.px(60), self.px(8), colors[si], e)
            texts = [self._disp(t.text) for t in toks]
            block = self._fit(texts, card_w - self.px(60), card_h - self.px(90), self.px(96), lh_factor=1.1)
            ox = cx0 + (card_w - block.width) / 2
            oy = cy + (card_h - block.height) / 2 + self.px(10)
            for i, tok in enumerate(toks):
                pr = self._prog(lt, tok, scene)
                color = colors[si] if tok.emph else st.text
                self._draw_word(layer, texts[i], block.font.size, True, color, ox + block.pos[i][0], oy + block.pos[i][1], pr, "slide_up" if st.entrance != "fade" else "fade")
        vs_start = scene.meta.get("vs_start")
        if vs_start is not None:
            pvs = _clamp((lt - (float(vs_start) - scene.start)) / 0.4)
            r = self.px(70)
            if pvs > 0:
                circ = self._rounded(2 * r, 2 * r, r, (*st.accent2, 255))
                self._composite(layer, self._alpha(circ, ease_out_back(pvs) if pvs < 1 else 1.0), self.W / 2 - r, self.H * 0.5 - r)
                vw = get_font(True, int(r * 0.9)).getlength("VS")
                self._draw_word(layer, "VS", int(r * 0.9), True, st.ink, self.W / 2 - vw / 2, self.H * 0.5 - r * 0.62, pvs, "fade")

    def _draw_bullets_or_fallback(self, layer, scene, lt):
        if len(self._groups(scene)) < 2:
            return self._draw_title(layer, scene, lt)
        return self._draw_bullets(layer, scene, lt)

    def _scene_layer(self, scene: Scene, lt: float) -> Image.Image:
        layer = Image.new("RGBA", (self.W, self.H), (0, 0, 0, 0))
        if lt < 0:
            return layer
        kind = scene.kind
        if kind == "stat":
            self._draw_stat(layer, scene, lt)
        elif kind == "bullets":
            self._draw_bullets_or_fallback(layer, scene, lt)
        elif kind == "comparison":
            self._draw_comparison(layer, scene, lt)
        elif kind == "question":
            self._draw_question(layer, scene, lt)
        elif kind == "quote":
            self._draw_quote(layer, scene, lt)
        else:
            self._draw_title(layer, scene, lt)
        return layer

    def _caption_layer(self, t: float) -> Image.Image | None:
        if not self._chunks:
            return None
        ci = bisect_right(self._chunk_starts, t) - 1
        if ci < 0:
            return None
        chunk = self._chunks[ci]
        if t > chunk["end"] + 0.25:
            return None
        st = self.style
        layer = Image.new("RGBA", (self.W, self.H), (0, 0, 0, 0))
        words = chunk["words"]
        texts = [self._disp(w.text) for w in words]
        size = self.px(50)
        block = self._fit(texts, self.W * 0.86, self.H * 0.14, size, bold=True, min_scale=0.6)
        active = max((i for i, w in enumerate(words) if w.start <= t), default=0)
        bx = (self.W - block.width) / 2
        by = self.H * 0.86 - block.height / 2
        if st.caption_box:
            pad_x, pad_y = self.px(26), self.px(12)
            pill = self._rounded(block.width + 2 * pad_x, block.height + 2 * pad_y, self.px(22), st.caption_bg)
            self._composite(layer, pill, bx - pad_x, by - pad_y)
        base_color = st.caption_text if st.caption_box else st.text
        for i, w in enumerate(words):
            color = st.accent if i == active else base_color
            x = bx + block.pos[i][0]
            y = by + block.pos[i][1]
            self._composite(layer, self._text_img(texts[i], block.font.size, True, color), x, y)
        return layer

    # ------------------------------------------------------------ composición final
    def frame(self, t: float) -> Image.Image:
        """Frame RGBA en el instante t (segundos)."""
        base = self._bg.copy()
        base.alpha_composite(self._decor(t))
        idx = max(0, min(bisect_right(self.starts, t) - 1, len(self.scenes) - 1))
        cur = self.scenes[idx]
        lt = t - cur.start
        tr = min(TRANSITION, (cur.end - cur.start) / 2)
        st = self.style
        if idx > 0 and lt < tr and st.transition != "cut":
            prev = self.scenes[idx - 1]
            p = ease_out_cubic(lt / tr)
            prev_layer = self._scene_layer(prev, t - prev.start)
            cur_layer = self._scene_layer(cur, lt)
            if st.transition == "slide":
                self._composite(base, prev_layer, -p * self.W * 0.35, 0)
                self._composite(base, self._alpha(cur_layer, p), (1 - p) * self.W * 0.35, 0)
            elif st.transition == "zoom":
                k = 0.9 + 0.1 * p
                cur_layer = cur_layer.resize((max(1, int(self.W * k)), max(1, int(self.H * k))), Image.BICUBIC)
                cx, cy = (self.W - cur_layer.width) / 2, (self.H - cur_layer.height) / 2
                self._composite(base, self._alpha(prev_layer, 1 - p), 0, 0)
                self._composite(base, self._alpha(cur_layer, p), cx, cy)
            else:  # fade
                self._composite(base, self._alpha(prev_layer, 1 - p), 0, 0)
                self._composite(base, self._alpha(cur_layer, p), 0, 0)
        else:
            base.alpha_composite(self._scene_layer(cur, lt))
        cap = self._caption_layer(t)
        if cap is not None:
            base.alpha_composite(cap)
        if st.progress_bar:
            w = int(self.W * _clamp(t / self.duration))
            ImageDraw.Draw(base).rectangle((0, self.H - self.px(10), w, self.H), fill=(*st.accent, 255))
        return base

    def render_video(
        self,
        out_path: str | Path,
        audio_path: str | Path | None = None,
        progress: Callable[[float], None] | None = None,
    ) -> None:
        out_path = Path(out_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        cmd = [
            ffmpeg_path(), "-y", "-hide_banner", "-loglevel", "error",
            "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{self.W}x{self.H}", "-r", str(self.fps), "-i", "-",
        ]
        if audio_path:
            cmd += ["-i", str(audio_path), "-map", "0:v:0", "-map", "1:a:0?", "-c:a", "aac", "-b:a", "192k"]
        else:
            cmd += ["-map", "0:v:0"]
        cmd += [
            "-t", f"{self.duration:.3f}",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p",
            "-movflags", "+faststart", str(out_path),
        ]
        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
        total = max(1, int(round(self.duration * self.fps)))
        try:
            for i in range(total):
                frame = self.frame(i / self.fps).convert("RGB")
                proc.stdin.write(frame.tobytes())
                if progress and i % 15 == 0:
                    progress(i / total)
        except BrokenPipeError:
            pass
        finally:
            try:
                proc.stdin.close()
            except Exception:
                pass
        err = proc.stderr.read().decode("utf-8", "replace")
        rc = proc.wait()
        if rc != 0:
            raise RuntimeError(f"ffmpeg falló (código {rc}): {err[-800:]}")
        if progress:
            progress(1.0)
