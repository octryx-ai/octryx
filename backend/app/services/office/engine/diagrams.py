"""Flow diagrams as PNG pictures (Pillow) for Word documents, which embed raster images only."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont

FLOW_COLORS = ("#0F4C81", "#1F7A8C", "#3A7D44", "#8C5E34")
_FONT_CANDIDATES = ("DejaVuSans.ttf", "DejaVuSans-Bold.ttf", "Arial.ttf", "Helvetica.ttc")


def flow_steps(section: dict[str, Any], *, limit: int = 4) -> list[dict[str, str]]:
    raw_steps = section.get("steps") or section.get("nodes") or section.get("items") or []
    steps: list[dict[str, str]] = []
    for item in raw_steps if isinstance(raw_steps, list) else []:
        if isinstance(item, dict):
            title = str(item.get("title") or item.get("label") or "").strip()
            body = str(item.get("body") or item.get("text") or item.get("description") or "").strip()
        else:
            title, body = str(item).strip(), ""
        if title:
            steps.append({"title": title, "body": body})
        if len(steps) >= limit:
            break
    return steps


def _font(size: int) -> Any:
    for name in _FONT_CANDIDATES:
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default(size=size)


def _centered(draw: Any, center_x: float, y: float, text: str, font: Any, fill: str, max_width: int) -> None:
    while text and draw.textlength(text, font=font) > max_width:
        text = text[:-2] + "…" if len(text) > 2 else text[:-1]
    draw.text((center_x, y), text, font=font, fill=fill, anchor="mm")


def flow_png(steps: list[dict[str, str]], path: str | Path, *, width: int = 1200, height: int = 260) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    image = Image.new("RGB", (width, height), "#FFFFFF")
    draw = ImageDraw.Draw(image)
    margin, gap, box_height, top = 50, 28, 118, 70
    count = max(len(steps), 1)
    box_width = int((width - margin * 2 - gap * (count - 1)) / count)
    title_font, body_font = _font(26), _font(18)
    for index, step in enumerate(steps):
        x = margin + index * (box_width + gap)
        draw.rounded_rectangle((x, top, x + box_width, top + box_height), radius=26, fill=FLOW_COLORS[index % len(FLOW_COLORS)])
        center = x + box_width / 2
        _centered(draw, center, top + 44, step["title"], title_font, "#FFFFFF", box_width - 24)
        if step.get("body"):
            _centered(draw, center, top + 80, step["body"], body_font, "#F8FAFC", box_width - 24)
        if index < count - 1:
            middle = top + box_height / 2
            start = x + box_width
            draw.line((start, middle, start + gap - 8, middle), fill="#4B5563", width=5)
            draw.polygon([(start + gap - 8, middle - 9), (start + gap + 8, middle), (start + gap - 8, middle + 9)], fill="#4B5563")
    image.save(target, "PNG")
    return target


__all__ = ["FLOW_COLORS", "flow_png", "flow_steps"]
