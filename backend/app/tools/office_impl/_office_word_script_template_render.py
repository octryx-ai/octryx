"""Render section block for generated Word scripts."""

from __future__ import annotations


def _word_script_render_sections() -> str:
    return """\

def render_sections() -> int:
    table_count = 0
    diagram_count = 0
    for section in SECTIONS:
        if not isinstance(section, dict):
            continue
        layout = str(section.get("layout_type") or "paragraph").strip().lower()
        title = str(section.get("title") or "").strip()
        subtitle = str(section.get("subtitle") or "").strip()
        body_lines = text_lines(section.get("body"))
        bullets = text_lines(section.get("bullets") or section.get("items"))
        citation_numbers = _resolve_citation_numbers(section.get("citations") or section.get("source_ids") or section.get("sources"))
        citation_suffix = _format_inline_citation(citation_numbers)

        if layout == "title_page":
            if title:
                add_heading(title, 0, alignment="center")
            if subtitle:
                add_paragraph(subtitle, style="Subtitle", alignment="center")
            for line in body_lines:
                add_paragraph(line)
            continue

        if layout == "toc":
            add_toc(
                title=title or "Table of Contents",
                levels=str(section.get("levels") or "1-3").strip() or "1-3",
            )
            continue

        if title:
            add_heading(title, 1 if layout == "section" else 2)
        if subtitle:
            add_paragraph(subtitle)

        if layout in {"section", "paragraph", "callout"}:
            for line in body_lines:
                add_paragraph(f"{line}{citation_suffix}", style="Intense Quote" if layout == "callout" else "")
            continue

        if layout in {"bullets", "numbered"}:
            for number, item in enumerate(bullets or body_lines, start=1):
                blocks.add_list_item(DOC, DOC, f"{item}{citation_suffix}", numbered=layout == "numbered", number=number)
            continue

        if layout == "quote":
            quote = str(section.get("quote") or section.get("body") or "").strip()
            author = str(section.get("author") or "").strip()
            if quote:
                add_paragraph(f'"{quote}"{citation_suffix}', style="Quote")
            if author:
                add_paragraph(author, alignment="right")
            continue

"""


def _word_script_render_sections_visual_layouts() -> str:
    return """\
        if layout == "formula":
            for line in body_lines:
                add_paragraph(f"{line}{citation_suffix}")
            formula = str(section.get("formula") or "").strip()
            if formula:
                add_equation(formula)
            continue

        if layout == "table":
            for line in body_lines:
                add_paragraph(f"{line}{citation_suffix}")
            table_count += 1
            render_table(section)
            if citation_suffix:
                add_paragraph(f"Sources{citation_suffix}")
            continue

        if layout == "chart":
            for line in body_lines:
                add_paragraph(f"{line}{citation_suffix}")
            add_chart(section.get("chart") if isinstance(section.get("chart"), dict) else section)
            insight = str(section.get("insight") or section.get("caption") or "").strip()
            if insight:
                add_paragraph(f"{insight}{citation_suffix}")
            elif citation_suffix:
                add_paragraph(f"Source{citation_suffix}")
            continue

        if layout in {"diagram", "process_flow"}:
            for line in body_lines:
                add_paragraph(f"{line}{citation_suffix}")
            diagram_count += 1
            add_diagram(section, diagram_index=diagram_count, alt=title or f"Diagram {diagram_count}")
            insight = str(section.get("insight") or section.get("caption") or "").strip()
            if insight:
                add_paragraph(f"{insight}{citation_suffix}")
            elif citation_suffix:
                add_paragraph(f"Source{citation_suffix}")
            continue

        for line in body_lines or bullets:
            add_paragraph(f"{line}{citation_suffix}")
    _render_bibliography()
    return table_count


"""


def _word_script_main() -> str:
    return """\
def main() -> None:
    render_sections()
    save_document(DOC, OUTPUT)
    print(f"Done. Built document: {OUTPUT}")


if __name__ == "__main__":
    main()
"""


def render_word_script_template_render() -> str:
    """The generated script text, assembled from its blocks in script order."""
    return _word_script_render_sections() + _word_script_render_sections_visual_layouts() + _word_script_main()


__all__ = ["render_word_script_template_render"]
