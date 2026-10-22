"""Estilos de motion graphics (entrada del usuario). Añadir un estilo = añadir una entrada aquí."""

from __future__ import annotations

from dataclasses import asdict, dataclass

RGB = tuple[int, int, int]
RGBA = tuple[int, int, int, int]


@dataclass(frozen=True)
class Style:
    key: str
    name: str
    description: str
    bg_top: RGB
    bg_bottom: RGB
    text: RGB
    muted: RGB
    accent: RGB
    accent2: RGB
    ink: RGB  # color de texto sobre el acento (cajas resaltadas, indicadores)
    entrance: str  # slide_up | pop | fade | typewriter
    transition: str  # fade | slide | zoom | cut
    decor: tuple[str, ...]  # grid | particles | circles | lines
    layout: str  # center | left
    uppercase: bool
    glow: bool
    cards: bool
    card_color: RGBA
    emph_box: bool  # palabras resaltadas con caja de color
    caption_box: bool  # subtítulos sobre una píldora
    progress_bar: bool
    swatch: tuple[RGB, RGB, RGB]  # colores para la tarjeta de selección en la UI
    caption_bg: RGBA = (0, 0, 0, 160)  # píldora de subtítulos
    caption_text: RGB = (255, 255, 255)  # texto de subtítulos sobre la píldora

    def public(self) -> dict:
        d = asdict(self)
        d["decor"] = list(self.decor)
        d["swatch"] = [list(c) for c in self.swatch]
        return d


STYLES: dict[str, Style] = {}


def _register(style: Style) -> None:
    STYLES[style.key] = style


_register(
    Style(
        key="neon_tech",
        name="Neon Tech",
        description="Fondo oscuro, cuadrícula y resplandor neón. Ideal para tecnología, IA y programación.",
        bg_top=(9, 12, 28),
        bg_bottom=(30, 8, 52),
        text=(240, 244, 255),
        muted=(150, 160, 195),
        accent=(0, 229, 255),
        accent2=(255, 46, 136),
        ink=(8, 10, 20),
        entrance="slide_up",
        transition="slide",
        decor=("grid", "particles"),
        layout="center",
        uppercase=False,
        glow=True,
        cards=True,
        card_color=(255, 255, 255, 16),
        emph_box=False,
        caption_box=True,
        progress_bar=True,
        swatch=((9, 12, 28), (0, 229, 255), (255, 46, 136)),
    )
)
_register(
    Style(
        key="editorial_minimal",
        name="Editorial minimalista",
        description="Fondo crema, tipografía limpia y líneas finas. Ideal para ensayo, historia y divulgación.",
        bg_top=(248, 246, 241),
        bg_bottom=(236, 231, 222),
        text=(20, 20, 22),
        muted=(110, 108, 104),
        accent=(228, 87, 46),
        accent2=(30, 90, 140),
        ink=(255, 255, 255),
        entrance="fade",
        transition="fade",
        decor=("lines",),
        layout="left",
        uppercase=False,
        glow=False,
        cards=False,
        card_color=(0, 0, 0, 0),
        emph_box=False,
        caption_box=False,
        progress_bar=False,
        swatch=((248, 246, 241), (20, 20, 22), (228, 87, 46)),
    )
)
_register(
    Style(
        key="bold_pop",
        name="Bold Pop",
        description="Amarillo llamativo, mayúsculas y rebotes. Estilo de miniaturas y Shorts de alta energía.",
        bg_top=(255, 214, 66),
        bg_bottom=(255, 180, 0),
        text=(18, 18, 18),
        muted=(70, 55, 10),
        accent=(255, 59, 59),
        accent2=(18, 18, 18),
        ink=(255, 255, 255),
        entrance="pop",
        transition="zoom",
        decor=("circles",),
        layout="center",
        uppercase=True,
        glow=False,
        cards=True,
        card_color=(255, 255, 255, 255),
        emph_box=True,
        caption_box=True,
        progress_bar=False,
        swatch=((255, 214, 66), (18, 18, 18), (255, 59, 59)),
        caption_bg=(18, 18, 18, 235),
        caption_text=(255, 255, 255),
    )
)
_register(
    Style(
        key="corporate_clean",
        name="Corporativo limpio",
        description="Degradado azul, formas redondeadas y transiciones deslizantes. Ideal para negocios y finanzas.",
        bg_top=(12, 58, 110),
        bg_bottom=(28, 111, 184),
        text=(255, 255, 255),
        muted=(200, 222, 242),
        accent=(255, 183, 3),
        accent2=(120, 220, 255),
        ink=(12, 40, 80),
        entrance="slide_up",
        transition="slide",
        decor=("circles", "lines"),
        layout="left",
        uppercase=False,
        glow=False,
        cards=True,
        card_color=(255, 255, 255, 34),
        emph_box=False,
        caption_box=True,
        progress_bar=True,
        swatch=((12, 58, 110), (255, 255, 255), (255, 183, 3)),
    )
)


def get_style(key: str) -> Style:
    if key not in STYLES:
        raise KeyError(f"Estilo desconocido: {key}. Disponibles: {', '.join(STYLES)}")
    return STYLES[key]
