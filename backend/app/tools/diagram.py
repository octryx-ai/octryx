"""Diagram generation tools for creating and editing draw.io diagrams.

Key design (ported from next-ai-draw-io approach):
- LLM generates ONLY <mxCell> elements — no wrapper tags needed
- Backend wraps cells into complete mxGraphModel XML automatically
- Multi-step auto-repair handles all common LLM mistakes
- Truncation detection for large diagrams
"""

import re
import uuid
from typing import Any
from xml.etree import ElementTree

from ._diagram_shape_library import available_shape_libraries, load_shape_library, shape_library_exists
from .context import ToolContext

# Mandatory root cells that draw.io requires
_ROOT_CELLS = '<mxCell id="0"/><mxCell id="1" parent="0"/>'

# ─── XML helpers ─────────────────────────────────────────────────────────────


def _strip_code_fences(xml: str) -> str:
    xml = xml.strip()
    xml = re.sub(r"^```(?:xml)?\s*", "", xml, flags=re.MULTILINE)
    xml = re.sub(r"\s*```\s*$", "", xml, flags=re.MULTILINE)
    return xml.strip()


def _auto_fix_xml(xml: str) -> tuple[str, list[str]]:
    """Port of next-ai-draw-io autoFixXml — 24-step repair pipeline."""
    fixed = xml
    fixes: list[str] = []

    # 0. Fix JSON-escaped XML (model sometimes double-escapes)
    if '\\"' in fixed:
        fixed = fixed.replace('\\"', '"').replace("\\n", "\n")
        fixes.append("Fixed JSON-escaped XML")

    # 1. Strip leading/trailing whitespace
    fixed = fixed.strip()

    # 2. Remove CDATA wrapper if present
    if "<![CDATA[" in fixed:
        fixed = re.sub(r"<!\[CDATA\[", "", fixed)
        fixed = re.sub(r"\]\]>", "", fixed)
        fixes.append("Removed CDATA wrapper")

    # 3. Remove text before first XML tag
    first_tag = fixed.find("<")
    if first_tag > 0:
        fixed = fixed[first_tag:]
        fixes.append("Removed leading non-XML text")

    # 4. LLM wrote </Cell> instead of </mxCell>
    if "</Cell>" in fixed:
        fixed = re.sub(r"</Cell>", "</mxCell>", fixed)
        fixes.append("Fixed </Cell> → </mxCell>")

    # 5. LLM wrote <Cell instead of <mxCell (opening tags)
    if re.search(r"<Cell\b", fixed):
        fixed = re.sub(r"<Cell\b", "<mxCell", fixed)
        fixes.append("Fixed <Cell → <mxCell")

    # 6. Fix unescaped & in attribute values
    fixed = re.sub(r"&(?!(?:amp|lt|gt|quot|apos|#\d+|#x[0-9a-fA-F]+);)", "&amp;", fixed)
    if "&amp;" in fixed and "Fixed unescaped &" not in fixes:
        fixes.append("Escaped bare & characters")

    # 7. Strip full wrapper if LLM included it (we add wrapper ourselves)
    if "<mxfile" in fixed:
        m = re.search(r"<mxGraphModel[^>]*>(.*?)</mxGraphModel>", fixed, re.DOTALL)
        if m:
            inner = re.search(r"<root>(.*?)</root>", m.group(0), re.DOTALL)
            if inner:
                fixed = inner.group(1).strip()
                fixes.append("Stripped mxfile/mxGraphModel/root wrapper — extracted cells")

    elif "<mxGraphModel" in fixed:
        inner = re.search(r"<root>(.*?)</root>", fixed, re.DOTALL)
        if inner:
            fixed = inner.group(1).strip()
            fixes.append("Stripped mxGraphModel/root wrapper — extracted cells")

    elif fixed.startswith("<root>"):
        fixed = re.sub(r"^<root>\s*", "", fixed)
        fixed = re.sub(r"\s*</root>\s*$", "", fixed)
        fixes.append("Stripped <root> wrapper")

    # 8. Remove the mandatory root cells if LLM included them (we add them)
    fixed = re.sub(r'<mxCell[^>]*\bid=["\']0["\'][^>]*/>', "", fixed)
    fixed = re.sub(r'<mxCell[^>]*\bid=["\']0["\'][^>]*></mxCell>', "", fixed)
    fixed = re.sub(r'<mxCell[^>]*\bid=["\']1["\'][^>]*/>', "", fixed)
    fixed = re.sub(r'<mxCell[^>]*\bid=["\'][0-9]*["\'][^>]*parent=["\']0["\'][^>]*/>', "", fixed)

    # 9. Visible cells must live under layer id=1; id=0 is the hidden root.
    parent_zero_pattern = re.compile(
        r"(<mxCell\b(?=[^>]*(?:\bvertex=[\"']1[\"']|\bedge=[\"']1[\"']))[^>]*\bparent=)([\"'])0\2"
    )

    def _normalize_visible_parent(match: re.Match[str]) -> str:
        return f"{match.group(1)}{match.group(2)}1{match.group(2)}"

    fixed, parent_fix_count = parent_zero_pattern.subn(_normalize_visible_parent, fixed)
    if parent_fix_count:
        fixes.append("Normalized visible mxCell parent=0 to parent=1")

    # 10. Trim trailing wrapper closing tags the LLM sometimes appends
    fixed = re.sub(r"\s*(</root>|</mxGraphModel>|</diagram>|</mxfile>)\s*$", "", fixed).strip()

    # 11. Fix self-closing mxGeometry that has a redundant closing tag
    fixed = re.sub(r"(<mxGeometry[^>]+/)>\s*</mxGeometry>", r"\1>", fixed)

    # 12. Fix missing self-close slash on empty mxGeometry
    fixed = re.sub(r"(<mxGeometry[^/]*)></mxGeometry>", r"\1/>", fixed)

    # 13. Some models put the cell id into vertex/edge instead of using id="...".
    # Draw.io accepts the XML text but cannot render those cells correctly.
    fixed, identity_attr_fixes = _repair_misused_mxcell_identity_attrs(fixed)
    fixes.extend(identity_attr_fixes)

    # 14. Add required ids/parents when models omit them on otherwise valid cells.
    fixed, required_attr_fixes = _repair_missing_required_mxcell_attrs(fixed)
    fixes.extend(required_attr_fixes)

    # 15. Common AWS style typo from weaker models.
    fixed, resicon_fix_count = re.subn(r"\bresC=", "resIcon=", fixed)
    if resicon_fix_count:
        fixes.append("Fixed AWS style typo resC= → resIcon=")

    return fixed.strip(), fixes


_BOOLEAN_MXCELL_ATTR_VALUES = {"0", "1", "true", "false"}
_MXCELL_OPEN_TAG_PATTERN = re.compile(r"<mxCell\b(?P<attrs>[^>]*)>", re.DOTALL)


def _get_xml_attr(attrs: str, name: str) -> str | None:
    match = re.search(rf"\b{re.escape(name)}=(['\"])(.*?)\1", attrs, flags=re.DOTALL)
    return match.group(2) if match else None


def _set_xml_attr(attrs: str, name: str, value: str) -> str:
    pattern = re.compile(rf"(\b{re.escape(name)}=)(['\"])(.*?)\2", flags=re.DOTALL)
    if pattern.search(attrs):
        return pattern.sub(rf'\1"{value}"', attrs, count=1)
    return f'{attrs} {name}="{value}"'


def _repair_misused_mxcell_identity_attrs(xml: str) -> tuple[str, list[str]]:
    fixes: list[str] = []
    repaired_vertex_count = 0
    repaired_edge_count = 0

    def _repair_tag(match: re.Match[str]) -> str:
        nonlocal repaired_vertex_count, repaired_edge_count
        attrs = match.group("attrs")
        if _get_xml_attr(attrs, "id"):
            return match.group(0)

        vertex_value = (_get_xml_attr(attrs, "vertex") or "").strip()
        if vertex_value and vertex_value.lower() not in _BOOLEAN_MXCELL_ATTR_VALUES:
            attrs = f' id="{vertex_value}"' + _set_xml_attr(attrs, "vertex", "1")
            repaired_vertex_count += 1
            return f"<mxCell{attrs}>"

        edge_value = (_get_xml_attr(attrs, "edge") or "").strip()
        if edge_value and edge_value.lower() not in _BOOLEAN_MXCELL_ATTR_VALUES:
            attrs = f' id="{edge_value}"' + _set_xml_attr(attrs, "edge", "1")
            repaired_edge_count += 1
            return f"<mxCell{attrs}>"

        return match.group(0)

    fixed = _MXCELL_OPEN_TAG_PATTERN.sub(_repair_tag, xml)
    if repaired_vertex_count:
        fixes.append("Moved non-boolean vertex values into mxCell id attributes")
    if repaired_edge_count:
        fixes.append("Moved non-boolean edge values into mxCell id attributes")
    return fixed, fixes


def _repair_missing_required_mxcell_attrs(xml: str) -> tuple[str, list[str]]:
    fixes: list[str] = []
    generated_id_count = 0
    generated_parent_count = 0
    auto_index = 0

    def _repair_tag(match: re.Match[str]) -> str:
        nonlocal auto_index, generated_id_count, generated_parent_count
        attrs = match.group("attrs")
        vertex_value = (_get_xml_attr(attrs, "vertex") or "").strip().lower()
        edge_value = (_get_xml_attr(attrs, "edge") or "").strip().lower()
        is_visible_vertex = vertex_value in {"1", "true"}
        is_edge = edge_value in {"1", "true"}
        if not is_visible_vertex and not is_edge:
            return match.group(0)

        if not _get_xml_attr(attrs, "id"):
            auto_index += 1
            prefix = "edge_auto" if is_edge else "node_auto"
            attrs = f' id="{prefix}_{auto_index}"' + attrs
            generated_id_count += 1

        if not _get_xml_attr(attrs, "parent"):
            attrs = _set_xml_attr(attrs, "parent", "1")
            generated_parent_count += 1

        return f"<mxCell{attrs}>"

    fixed = _MXCELL_OPEN_TAG_PATTERN.sub(_repair_tag, xml)
    if generated_id_count:
        fixes.append("Added missing mxCell id attributes")
    if generated_parent_count:
        fixes.append("Added missing visible mxCell parent attributes")
    return fixed, fixes


def _wrap_cells(cells_xml: str) -> str:
    """Wrap bare mxCell elements into a complete mxGraphModel document."""
    return f"<mxGraphModel><root>{_ROOT_CELLS}{cells_xml}</root></mxGraphModel>"


def _is_complete(xml: str) -> bool:
    """Detect truncated output — last valid mxCell should be followed only by closing tags."""
    trimmed = xml.strip()
    if not trimmed:
        return False
    last_self = trimmed.rfind("/>")
    last_close = trimmed.rfind("</mxCell>")
    last_valid = max(last_self, last_close)
    if last_valid == -1:
        return False
    offset = 9 if last_close > last_self else 2
    suffix = trimmed[last_valid + offset :]
    return bool(re.match(r"^(\s*</[^>]+>)*\s*$", suffix))


def _validate_wrapped_xml(full_xml: str) -> str | None:
    """Parse the full wrapped XML. Returns error string or None if valid."""
    try:
        ElementTree.fromstring(full_xml)
        return None
    except ElementTree.ParseError as e:
        return str(e)


# ─── Tools ───────────────────────────────────────────────────────────────────


class CreateDiagramTool:
    name = "create_diagram"
    description = "".join(
        [
            "Create a draw.io diagram. ",
            "The 'xml' parameter must contain ONLY <mxCell> elements — ",
            "do NOT include <mxGraphModel>, <root>, <mxfile>, or root cells with id='0'/'1'. ",
            "Those are added automatically. ",
            "Example of what to pass: ",
            (
                '<mxCell id="n1" value="EKS" style="rounded=1;whiteSpace=wrap;html=1;'
                'fillColor=#FF9900;strokeColor=#232F3E;fontColor=#ffffff;" vertex="1" parent="1">'
                '<mxGeometry x="80" y="80" width="160" height="60" as="geometry"/></mxCell>'
            ),
            (
                '<mxCell id="n2" value="SQS" style="rounded=1;whiteSpace=wrap;html=1;'
                'fillColor=#FF9900;strokeColor=#232F3E;fontColor=#ffffff;" vertex="1" parent="1">'
                '<mxGeometry x="320" y="80" width="160" height="60" as="geometry"/></mxCell>'
            ),
            (
                '<mxCell id="e1" edge="1" source="n1" target="n2" parent="1">'
                '<mxGeometry relative="1" as="geometry"/></mxCell>'
            ),
            " — that is all you need. Space nodes 200px apart. ",
            "For AWS services use fillColor=#FF9900;strokeColor=#232F3E;fontColor=#ffffff. ",
            "For databases use shape=cylinder3;fillColor=#dae8fc;strokeColor=#6c8ebf. ",
            "CRITICAL: close every <mxCell with </mxCell>, never </Cell>.",
        ]
    )

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        raw: str = params.get("xml", "")
        title: str = str(params.get("title", "Diagram")).strip() or "Diagram"

        raw = _strip_code_fences(raw)
        if not raw:
            return {
                "error": "xml parameter is empty — pass the mxCell elements as shown in the tool description",
                "example": (
                    '<mxCell id="n1" value="EKS" style="rounded=1;whiteSpace=wrap;html=1;" '
                    'vertex="1" parent="1"><mxGeometry x="80" y="80" width="160" height="60" '
                    'as="geometry"/></mxCell>'
                ),
            }

        cells, fixes = _auto_fix_xml(raw)

        if not _is_complete(cells):
            return {
                "error": (
                    "XML appears truncated — the last mxCell was not properly closed. Call append_diagram to continue."
                ),
                "partial": True,
            }

        full_xml = _wrap_cells(cells)
        parse_error = _validate_wrapped_xml(full_xml)
        if parse_error:
            return {
                "error": f"XML parse error after auto-repair: {parse_error}",
                "hint": "Check that every <mxCell has a matching </mxCell> closing tag. Never write </Cell>.",
                "auto_fixes_applied": fixes,
            }

        return {
            "status": "created",
            "diagram_id": str(uuid.uuid4())[:8],
            "title": title,
            "diagram_xml": full_xml,
            "format": "drawio",
            "auto_fixes_applied": fixes,
            "message": f"Diagram '{title}' created successfully.",
        }


class GetShapeLibraryTool:
    name = "get_shape_library"
    description = (
        "Load draw.io shape library documentation with exact style syntax and available shape names. "
        "Use this before create_diagram for vendor-specific or icon-specific diagrams such as AWS, Azure, GCP, "
        "Kubernetes, Cisco, BPMN, and network diagrams. "
        "Example libraries: aws4, azure2, gcp2, kubernetes, network, flowchart."
    )

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        library = str(params.get("library", "")).strip().lower()
        raw_shape_names = params.get("shape_names") or []
        requested_shape_names = [str(item).strip() for item in raw_shape_names if str(item).strip()]
        sanitized_library = re.sub(r"[^a-z0-9_-]", "", library)
        available_libraries = available_shape_libraries()

        if not sanitized_library:
            return {
                "error": "library parameter is required",
                "available_libraries": available_libraries,
            }
        if sanitized_library != library:
            return {
                "error": f"Invalid library name '{library}'. Use only letters, numbers, underscores, and hyphens.",
                "available_libraries": available_libraries,
            }

        if not shape_library_exists(sanitized_library):
            return {
                "error": f'Library "{library}" not found.',
                "available_libraries": available_libraries,
            }

        return {
            "library": sanitized_library,
            **load_shape_library(sanitized_library, requested_shape_names),
            "available_libraries": available_libraries,
        }


class AppendDiagramTool:
    name = "append_diagram"
    description = (
        "Continue generating diagram XML when create_diagram was truncated. "
        "Pass ONLY the continuation mxCell elements — no wrapper tags. "
        "Use this only after create_diagram returned a truncation error. "
        "Do NOT restart with wrapper tags like <mxGraphModel> or <root>."
    )

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        continuation: str = params.get("xml", "")
        base: str = params.get("base_xml", "")
        title: str = str(params.get("title", "Diagram")).strip() or "Diagram"

        continuation = _strip_code_fences(continuation)

        # Detect if model incorrectly restarted with wrapper tags
        trimmed = continuation.strip()
        bad_starts = ("<mxGraphModel", "<root", "<mxfile", 'id="0"', "id='0'")
        if any(trimmed.startswith(b) for b in bad_starts):
            return {
                "error": "Do not restart with wrapper tags. Pass ONLY continuation mxCell elements.",
            }

        combined = (base + "\n" + continuation).strip()
        combined, fixes = _auto_fix_xml(combined)

        if not _is_complete(combined):
            return {
                "status": "partial",
                "partial_xml": combined,
                "message": "Still incomplete. Call append_diagram again with more mxCell elements.",
            }

        full_xml = _wrap_cells(combined)
        parse_error = _validate_wrapped_xml(full_xml)
        if parse_error:
            return {"error": f"XML parse error: {parse_error}", "auto_fixes_applied": fixes}

        return {
            "status": "created",
            "diagram_id": str(uuid.uuid4())[:8],
            "title": title,
            "diagram_xml": full_xml,
            "format": "drawio",
            "message": f"Diagram '{title}' completed.",
        }


class EditDiagramTool:
    name = "edit_diagram"
    description = (
        "Update an existing diagram. Pass the COMPLETE new set of mxCell elements "
        "(same format as create_diagram — no wrapper tags). "
        "The entire diagram will be replaced. "
        "Use 'change_description' to briefly describe what changed."
    )

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        raw: str = params.get("xml", "")
        title: str = str(params.get("title", "Diagram")).strip() or "Diagram"
        change_description: str = str(params.get("change_description", "Updated")).strip()

        raw = _strip_code_fences(raw)
        if not raw:
            return {"error": "xml parameter is empty"}

        cells, fixes = _auto_fix_xml(raw)
        full_xml = _wrap_cells(cells)
        parse_error = _validate_wrapped_xml(full_xml)
        if parse_error:
            return {
                "error": f"XML parse error: {parse_error}",
                "hint": "Check all <mxCell> closing tags.",
                "auto_fixes_applied": fixes,
            }

        return {
            "status": "updated",
            "diagram_id": str(uuid.uuid4())[:8],
            "title": title,
            "diagram_xml": full_xml,
            "format": "drawio",
            "change_description": change_description,
            "message": f"Diagram updated: {change_description}",
        }
