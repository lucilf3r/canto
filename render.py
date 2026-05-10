"""
Render code blocks and HTML tables to PNG bytes using Pillow.
These images are injected into the ContentBlock stream so they display
in the image panel and are skipped by the TTS narrator.
"""
from __future__ import annotations

import io
import subprocess
import textwrap
from typing import Optional

from PIL import Image, ImageDraw, ImageFont
from bs4 import Tag


# ── Font helpers ──────────────────────────────────────────────────────────────

def _fc_match(family: str) -> str:
    """Ask fontconfig for the best match; fall back gracefully."""
    try:
        out = subprocess.check_output(
            ['fc-match', family, 'file'], stderr=subprocess.DEVNULL, text=True
        )
        for part in out.strip().split(':'):
            part = part.strip()
            if part.startswith('file='):
                return part[5:]
            if part.endswith('.ttf') or part.endswith('.otf'):
                return part
    except Exception:
        pass
    return ''


def _load_font(family: str, size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    path = _fc_match(family)
    if path:
        try:
            return ImageFont.truetype(path, size)
        except Exception:
            pass
    return ImageFont.load_default()


# ── Code block renderer ───────────────────────────────────────────────────────

CODE_BG   = (24, 27, 33)
CODE_FG   = (201, 209, 217)
CODE_PAD  = 16
CODE_LS   = 5     # extra line spacing px


def render_code(text: str, max_width_px: int = 860) -> bytes:
    """Render a code/pre block to PNG bytes."""
    font = _load_font('monospace', 13)

    # Measure a single character to estimate wrapping
    dummy = Image.new('RGB', (1, 1))
    d = ImageDraw.Draw(dummy)

    def text_size(s: str):
        bb = d.textbbox((0, 0), s or ' ', font=font)
        return bb[2] - bb[0], bb[3] - bb[1]

    char_w, char_h = text_size('W')
    usable_px = max_width_px - CODE_PAD * 2
    wrap_chars = max(20, usable_px // max(char_w, 1))

    lines: list[str] = []
    for raw in text.rstrip().split('\n'):
        if len(raw) <= wrap_chars:
            lines.append(raw)
        else:
            # Preserve indentation on wrapped continuation lines
            indent = len(raw) - len(raw.lstrip())
            wrapped = textwrap.wrap(raw, wrap_chars,
                                    subsequent_indent=' ' * indent)
            lines.extend(wrapped or [raw])

    if not lines:
        lines = ['']

    line_h = char_h + CODE_LS
    img_w = min(max(text_size(ln)[0] for ln in lines) + CODE_PAD * 2, max_width_px)
    img_h = len(lines) * line_h + CODE_PAD * 2

    img = Image.new('RGB', (img_w, img_h), color=CODE_BG)
    draw = ImageDraw.Draw(img)

    y = CODE_PAD
    for line in lines:
        draw.text((CODE_PAD, y), line, fill=CODE_FG, font=font)
        y += line_h

    buf = io.BytesIO()
    img.save(buf, format='PNG')
    return buf.getvalue()


# ── Table renderer ────────────────────────────────────────────────────────────

TBL_BG        = (22, 27, 34)
TBL_HEADER_BG = (32, 42, 58)
TBL_FG        = (201, 209, 217)
TBL_HEADER_FG = (255, 255, 255)
TBL_BORDER    = (48, 60, 76)
TBL_PAD_X     = 12
TBL_PAD_Y     = 7
MAX_COL_PX    = 220


def render_table(table_tag: Tag) -> Optional[bytes]:
    """Render an HTML <table> to PNG bytes. Returns None if table is empty."""
    # ── Parse rows ────────────────────────────────────────────────────────────
    rows: list[list[tuple[str, bool]]] = []   # [(text, is_header), ...]
    for tr in table_tag.find_all('tr'):
        row = [
            (cell.get_text(' ', strip=True), cell.name == 'th')
            for cell in tr.find_all(['th', 'td'])
        ]
        if row:
            rows.append(row)

    if not rows:
        return None

    n_cols = max(len(r) for r in rows)

    # ── Fonts ─────────────────────────────────────────────────────────────────
    font_h = _load_font('sans-serif:weight=bold', 13)
    font   = _load_font('sans-serif', 13)

    dummy = Image.new('RGB', (1, 1))
    d = ImageDraw.Draw(dummy)

    def cell_size(text: str, header: bool):
        bb = d.textbbox((0, 0), text or ' ', font=font_h if header else font)
        return bb[2] - bb[0], bb[3] - bb[1]

    # ── Measure column widths & row heights ───────────────────────────────────
    col_w = [0] * n_cols
    row_h: list[int] = []

    for row in rows:
        rh = 0
        for ci, (txt, is_h) in enumerate(row):
            if ci >= n_cols:
                break
            tw, th = cell_size(txt, is_h)
            col_w[ci] = max(col_w[ci], min(tw + TBL_PAD_X * 2, MAX_COL_PX))
            rh = max(rh, th + TBL_PAD_Y * 2)
        row_h.append(max(rh, 28))

    total_w = sum(col_w) + 1
    total_h = sum(row_h) + 1

    img = Image.new('RGB', (total_w, total_h), color=TBL_BG)
    draw = ImageDraw.Draw(img)

    # ── Draw cells ────────────────────────────────────────────────────────────
    y = 0
    for row, rh in zip(rows, row_h):
        x = 0
        for ci in range(n_cols):
            cw = col_w[ci]
            txt, is_h = row[ci] if ci < len(row) else ('', False)
            bg = TBL_HEADER_BG if is_h else TBL_BG
            fg = TBL_HEADER_FG if is_h else TBL_FG
            fn = font_h if is_h else font

            draw.rectangle([x, y, x + cw, y + rh], fill=bg, outline=TBL_BORDER)

            # Clip text that's too wide for the column
            max_chars = max(1, (cw - TBL_PAD_X * 2) // max(cell_size('W', is_h)[0], 1))
            display = txt if len(txt) <= max_chars else txt[:max_chars - 1] + '…'
            draw.text((x + TBL_PAD_X, y + TBL_PAD_Y), display, fill=fg, font=fn)
            x += cw
        y += rh

    buf = io.BytesIO()
    img.save(buf, format='PNG')
    return buf.getvalue()
