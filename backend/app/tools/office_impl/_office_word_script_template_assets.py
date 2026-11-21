"""Table, chart and diagram block for generated Word scripts."""

from __future__ import annotations


def render_word_script_template_assets() -> str:
    return """\

def render_table(section: dict[str, object]) -> None:
    headers = [str(item).strip() for item in (section.get("headers") or []) if str(item).strip()]
    rows = [[str(cell).strip() for cell in row] for row in (section.get("rows") or []) if isinstance(row, list)]
    if not headers and not rows:
        return
    blocks.add_table(DOC, DOC, headers=headers, rows=rows)


def add_chart(chart: dict[str, object]) -> None:
    if not isinstance(chart, dict):
        return
    try:
        spec = chart_spec(chart)
        add_docx_chart(DOC, spec, paragraph=DOC.add_paragraph(), cx=length_emu("15cm"), cy=length_emu("8.5cm"))
    except OfficeEngineError as exc:
        print(f"chart skipped: {exc}")


def add_diagram(section: dict[str, object], *, diagram_index: int, alt: str) -> None:
    steps = flow_steps(section)
    if not steps:
        return
    picture = flow_png(steps, OUTPUT.parent / f"{OUTPUT.stem}.assets" / f"diagram-{diagram_index}.png")
    blocks.add_picture(DOC.add_paragraph(), str(picture), width="6.6in", alt=alt)
"""


__all__ = ["render_word_script_template_assets"]
