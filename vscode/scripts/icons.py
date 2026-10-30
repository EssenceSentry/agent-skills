"""Build media/ax-icons.woff: each tool's mark, beside its usage in the status bar.

VS Code's own icons have none for these, so the extension contributes them (package.json
`contributes.icons`): `ax-claude` at U+E001 and `ax-codex` at U+E002, each the tool's own
mark, read from its VS Code extension installed on this Mac. They are never kept in this
repository: the font is built when the extension is packaged, and ignored.

    uv run --no-project --with fonttools --with skia-pathops python scripts/icons.py
"""

import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import pathops
from fontTools.fontBuilder import FontBuilder
from fontTools.pens.cu2quPen import Cu2QuPen
from fontTools.pens.transformPen import TransformPen
from fontTools.pens.ttGlyphPen import TTGlyphPen
from fontTools.svgLib.path import SVGPath

EM = 1000
FIT = 0.75  # each mark's larger side, as a share of the font's square: a little under the text
EXTENSIONS = Path("~/.vscode/extensions").expanduser()
OUT = Path(__file__).resolve().parent.parent / "media" / "ax-icons.woff"
MARKS = {  # glyph: (its extension, its mark, its code point)
    "ax-claude": ("anthropic.claude-code-*", "resources/claude-logo.svg", 0xE001),
    "ax-codex": ("openai.chatgpt-*", "resources/blossom-black.svg", 0xE002),
}


def mark(extension: str, file: str) -> Path:
    """The mark in the newest installed version of the tool's extension."""
    found = sorted(EXTENSIONS.glob(f"{extension}/{file}"))
    if not found:
        sys.exit(f"no {file} in {EXTENSIONS}/{extension}: install that extension first")
    return found[-1]


def outline(svg: Path) -> pathops.Path:
    """The mark's outline, its y-axis turned upright."""
    root = ET.parse(svg).getroot()
    left, top, width, height = (float(v) for v in (root.get("viewBox") or "0 0 24 24").split())
    path = pathops.Path()
    SVGPath(
        str(svg),
        transform=(EM / width, 0, 0, -EM / height, -left * EM / width, EM + top * EM / height),
    ).draw(path.getPen())
    path.simplify(fix_winding=True)  # holes the way a font's filling rule keeps them
    return path


def glyph(path: pathops.Path):
    """The mark fitted, centred, into the font's square, so every mark reads the same size
    whatever room its drawing left around it."""
    x0, y0, x1, y1 = path.bounds
    scale = FIT * EM / max(x1 - x0, y1 - y0)
    dx = (EM - (x1 - x0) * scale) / 2 - x0 * scale
    dy = (EM - (y1 - y0) * scale) / 2 - y0 * scale
    pen = TTGlyphPen(None)
    path.draw(TransformPen(Cu2QuPen(pen, max_err=1.0), (scale, 0, 0, scale, dx, dy)))
    return pen.glyph()


def build() -> None:
    names = [".notdef", *MARKS]
    builder = FontBuilder(EM, isTTF=True)
    builder.setupGlyphOrder(names)
    builder.setupCharacterMap({point: name for name, (_, _, point) in MARKS.items()})
    glyphs = {".notdef": TTGlyphPen(None).glyph()}
    for name, (extension, file, _) in MARKS.items():
        glyphs[name] = glyph(outline(mark(extension, file)))
    builder.setupGlyf(glyphs)
    builder.setupHorizontalMetrics({name: (EM, 0) for name in names})
    builder.setupHorizontalHeader(ascent=EM, descent=0)
    builder.setupNameTable({"familyName": "ax icons", "styleName": "Regular"})
    builder.setupOS2(sTypoAscender=EM, sTypoDescender=0, usWinAscent=EM, usWinDescent=0)
    builder.setupPost()
    builder.font.flavor = "woff"
    OUT.parent.mkdir(parents=True, exist_ok=True)
    builder.save(str(OUT))
    print(f"wrote {OUT} ({OUT.stat().st_size} bytes)")


if __name__ == "__main__":
    build()
