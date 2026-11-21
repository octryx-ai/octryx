"""PowerPoint views: ``text``, ``outline``, ``annotated``, ``stats`` (the chat inspector's ``slides`` shapes)."""

from __future__ import annotations

from collections import Counter
from typing import Any

from .paths import EMU_PER_CM, text_window
from .slides import shape_paths, shape_type, typed_shapes
from .slides_describe import slide_title


def _shape_texts(slide: Any) -> list[str]:
    texts: list[str] = []
    for shape in slide.shapes:
        kind = shape_type(shape)
        if kind == "table":
            texts.extend(" | ".join(cell.text for cell in row.cells) for row in shape.table.rows)
        elif getattr(shape, "has_text_frame", False) and shape.has_text_frame and shape.text_frame.text.strip():
            texts.append(shape.text_frame.text)
    return texts


def _notes(slide: Any) -> str:
    if not slide.has_notes_slide or slide.notes_slide.notes_text_frame is None:
        return ""
    return slide.notes_slide.notes_text_frame.text


def _window(presentation: Any, start: int | None, end: int | None) -> list[tuple[int, Any]]:
    numbered = list(enumerate(presentation.slides, start=1))
    return text_window(numbered, start=start, end=end, max_lines=None)


def text_view(presentation: Any, *, start: int | None = None, end: int | None = None, max_lines: int | None = None) -> dict[str, Any]:
    slides = []
    for index, slide in _window(presentation, start, end):
        texts = _shape_texts(slide)
        slides.append({
            "index": index,
            "path": f"/slide[{index}]",
            "texts": texts[: int(max_lines)] if max_lines else texts,
            "notes": _notes(slide),
        })
    return {"totalSlides": len(presentation.slides), "slides": slides}


def outline_view(presentation: Any) -> dict[str, Any]:
    slides = []
    for index, slide in enumerate(presentation.slides, start=1):
        grouped = typed_shapes(slide)
        slides.append({
            "index": index,
            "title": slide_title(slide),
            "layout": slide.slide_layout.name,
            "textBoxes": sum(1 for shape in grouped["shape"] if shape.has_text_frame and shape.text_frame.text.strip()),
            "pictures": len(grouped["picture"]),
            "tables": len(grouped["table"]),
            "charts": len(grouped["chart"]),
        })
    return {"totalSlides": len(slides), "slides": slides}


def annotated_view(presentation: Any, *, start: int | None = None, end: int | None = None, max_lines: int | None = None) -> dict[str, Any]:
    lines: list[str] = []
    for index, slide in _window(presentation, start, end):
        lines.append(f"[/slide[{index}]] layout {slide.slide_layout.name!r}")
        for path, shape in shape_paths(slide, f"/slide[{index}]"):
            role = ""
            if shape.is_placeholder:
                role = f"{str(shape.placeholder_format.type).split(' ')[0].split('.')[-1].lower()} placeholder, "
            size = ""
            if getattr(shape, "has_text_frame", False) and shape.has_text_frame:
                sizes = {run.font.size.pt for p in shape.text_frame.paragraphs for run in p.runs if run.font.size}
                size = f", {'/'.join(f'{value:g}pt' for value in sorted(sizes))}" if sizes else ""
                text = shape.text_frame.text.replace("\n", " / ")
            else:
                text = ""
            geometry = f"{shape.left / EMU_PER_CM:.1f},{shape.top / EMU_PER_CM:.1f} {shape.width / EMU_PER_CM:.1f}x{shape.height / EMU_PER_CM:.1f}cm" if shape.width is not None else ""
            lines.append(f"    [{path}] ({role}{shape.name}, {geometry}{size}) {text}".rstrip())
        notes = _notes(slide)
        if notes.strip():
            lines.append(f"    [notes] {notes.replace(chr(10), ' / ')}")
    window = lines[: int(max_lines)] if max_lines else lines
    return {"Content": "\n".join(window), "totalLines": len(lines)}


def stats_view(presentation: Any) -> dict[str, Any]:
    layouts: Counter[str] = Counter()
    counts: Counter[str] = Counter()
    words = 0
    characters = 0
    for slide in presentation.slides:
        layouts[str(slide.slide_layout.name)] += 1
        for kind, items in typed_shapes(slide).items():
            counts[kind] += len(items)
        for text in _shape_texts(slide):
            words += len(text.split())
            characters += len(text)
    return {
        "slides": len(presentation.slides),
        "shapes": counts["shape"],
        "pictures": counts["picture"],
        "tables": counts["table"],
        "charts": counts["chart"],
        "words": words,
        "totalCharacters": characters,
        "slideWidthCm": round(presentation.slide_width / EMU_PER_CM, 2),
        "slideHeightCm": round(presentation.slide_height / EMU_PER_CM, 2),
        "layoutsUsed": dict(layouts.most_common()),
    }


__all__ = ["annotated_view", "outline_view", "stats_view", "text_view"]
