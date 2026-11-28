"""The tray image: the Octryx mascot as a silhouette for the menu bar's appearance, with a state badge."""

from __future__ import annotations

import base64
import io
from functools import lru_cache

from PIL import Image, ImageDraw, ImageFont

from . import icon_data

BADGE = {"working": "#2B6CFF", "needs_you": "#FF8D4D", "done": "#2EA44F", "problem": "#E5484D"}
FADED = frozenset({"offline", "signed_out"})
INK = {"light": (32, 26, 22), "dark": (242, 234, 224)}  # mascot colour on a light / dark menu bar
ICO_SIZES = (16, 20, 24, 32, 48, 64, 256)


@lru_cache(maxsize=1)
def _mascot() -> Image.Image:
    return Image.open(io.BytesIO(base64.b64decode("".join(icon_data.MASCOT_PNG)))).convert("RGBA")


def _silhouette(size: int, ink: tuple[int, int, int], opacity: float) -> Image.Image:
    alpha = _mascot().getchannel("A").resize((size, size), Image.LANCZOS)
    if opacity < 1:
        alpha = alpha.point(lambda value: int(value * opacity))
    image = Image.new("RGBA", (size, size), (*ink, 0))
    image.putalpha(alpha)
    return image


def _font(px: int) -> ImageFont.ImageFont:
    try:
        return ImageFont.load_default(size=px)
    except TypeError:  # an old Pillow without sized default fonts
        return ImageFont.load_default()


def _check(draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int], width: int) -> None:
    left, top, right, bottom = box
    w, h = right - left, bottom - top
    draw.line([(left + w * 0.27, top + h * 0.52), (left + w * 0.44, top + h * 0.70),
               (left + w * 0.74, top + h * 0.32)], fill="white", width=width, joint="curve")


def render(status: str, count: int = 0, *, size: int = 44, appearance: str = "light") -> Image.Image:
    ink = INK.get(appearance, INK["light"])
    image = _silhouette(size, ink, 0.45 if status in FADED else 1.0)
    draw = ImageDraw.Draw(image)
    if status in FADED:
        radius = size * 0.2
        centre = (size - radius - 1, size - radius - 1)
        box = [centre[0] - radius, centre[1] - radius, centre[0] + radius, centre[1] + radius]
        draw.ellipse(box, fill=(0, 0, 0, 0))
        draw.ellipse(box, outline=(140, 140, 140, 255), width=max(2, size // 16))
        return image
    colour = BADGE.get(status)
    if colour is None:
        return image
    small = status == "working"
    diameter = round(size * (0.36 if small else 0.52))
    box = (size - diameter, size - diameter, size - 1, size - 1)
    gap = max(1, size // 22)  # a transparent cut-out around the badge keeps it apart from the tentacles
    draw.ellipse([box[0] - gap, box[1] - gap, box[2] + gap, box[3] + gap], fill=(0, 0, 0, 0))
    draw.ellipse(box, fill=colour)
    if status == "needs_you" and count:
        text = "9+" if count > 9 else str(count)
        font = _font(round(diameter * (0.62 if len(text) == 1 else 0.5)))
        draw.text(((box[0] + box[2]) / 2, (box[1] + box[3]) / 2 + 0.5), text, fill="white", font=font, anchor="mm")
    elif status == "problem":
        font = _font(round(diameter * 0.7))
        draw.text(((box[0] + box[2]) / 2, (box[1] + box[3]) / 2 + 0.5), "!", fill="white", font=font, anchor="mm")
    elif status == "done":
        _check(draw, box, max(2, diameter // 7))
    return image


def ico_bytes(status: str, count: int = 0, *, appearance: str = "dark") -> bytes:
    buffer = io.BytesIO()
    render(status, count, size=256, appearance=appearance).save(buffer, "ICO", sizes=[(s, s) for s in ICO_SIZES])
    return buffer.getvalue()


__all__ = ["BADGE", "ICO_SIZES", "ico_bytes", "render"]
