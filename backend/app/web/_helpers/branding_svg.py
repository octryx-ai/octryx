"""Sanitizer for an inline SVG logo in the branding config: SVG elements and attributes on an allowlist only."""

import re
from xml.etree import ElementTree

_SVG_XML_DECLARATION_PATTERN = re.compile(r"^\s*<\?xml[^>]*\?>", re.IGNORECASE)
_SVG_LOCAL_FRAGMENT_PATTERN = re.compile(r"^url\(\s*#[A-Za-z_][A-Za-z0-9_.:-]*\s*\)$")
_SVG_ID_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_.:-]*$")
_SAFE_SVG_TAGS = {
    "svg",
    "g",
    "path",
    "circle",
    "ellipse",
    "rect",
    "line",
    "polyline",
    "polygon",
    "defs",
    "linearGradient",
    "radialGradient",
    "stop",
    "title",
    "desc",
    "clipPath",
    "mask",
}
_SAFE_SVG_ATTRS = {
    "aria-hidden",
    "clip-path",
    "clip-rule",
    "cx",
    "cy",
    "d",
    "fill",
    "fill-opacity",
    "fill-rule",
    "gradientTransform",
    "gradientUnits",
    "height",
    "id",
    "mask",
    "offset",
    "opacity",
    "points",
    "preserveAspectRatio",
    "r",
    "role",
    "rx",
    "ry",
    "spreadMethod",
    "stop-color",
    "stop-opacity",
    "stroke",
    "stroke-linecap",
    "stroke-linejoin",
    "stroke-miterlimit",
    "stroke-opacity",
    "stroke-width",
    "transform",
    "viewBox",
    "width",
    "x",
    "x1",
    "x2",
    "xmlns",
    "y",
    "y1",
    "y2",
}
_SAFE_SVG_TEXT_TAGS = {"title", "desc"}
_SAFE_SVG_ROOT_NAMESPACE = "http://www.w3.org/2000/svg"
_REJECTED_SVG_VALUE_TOKENS = ("javascript:", "vbscript:", "<", ">", "expression(")


def _svg_local_name(name: str) -> str:
    if name.startswith("{"):
        return name.split("}", 1)[1]
    return name


def _svg_namespace(name: str) -> str | None:
    if name.startswith("{"):
        return name[1:].split("}", 1)[0]
    return None


def _is_safe_svg_attr_value(attr_name: str, value: str) -> bool:
    normalized = value.strip()
    if not normalized:
        return True
    lowered = normalized.lower()
    if any(token in lowered for token in _REJECTED_SVG_VALUE_TOKENS):
        return False
    if attr_name in {"fill", "stroke", "clip-path", "mask"} and lowered.startswith("url("):
        return bool(_SVG_LOCAL_FRAGMENT_PATTERN.fullmatch(normalized))
    if "url(" in lowered:
        return False
    if attr_name == "id":
        return bool(_SVG_ID_PATTERN.fullmatch(normalized))
    if attr_name == "xmlns":
        return normalized == _SAFE_SVG_ROOT_NAMESPACE
    return True


def _sanitize_logo_svg(logo_svg: str) -> str:
    raw_svg = str(logo_svg or "").strip()
    if not raw_svg:
        return ""
    if len(raw_svg) > 20_000:
        raise ValueError("Inline SVG exceeds the maximum allowed size")

    stripped_svg = _SVG_XML_DECLARATION_PATTERN.sub("", raw_svg).strip()
    lowered = stripped_svg.lower()
    if "<!doctype" in lowered or "<!entity" in lowered:
        raise ValueError("Inline SVG must not contain document type declarations")

    try:
        root = ElementTree.fromstring(stripped_svg)
    except ElementTree.ParseError as exc:
        raise ValueError("Inline SVG must be valid XML") from exc

    root_name = _svg_local_name(root.tag)
    root_namespace = _svg_namespace(root.tag)
    if root_name != "svg":
        raise ValueError("Inline SVG root element must be <svg>")
    if root_namespace not in {None, _SAFE_SVG_ROOT_NAMESPACE}:
        raise ValueError("Inline SVG must use the SVG namespace")

    for element in root.iter():
        tag_name = _svg_local_name(element.tag)
        tag_namespace = _svg_namespace(element.tag)
        if tag_namespace not in {None, _SAFE_SVG_ROOT_NAMESPACE}:
            raise ValueError("Inline SVG must not contain foreign namespaces")
        if tag_name not in _SAFE_SVG_TAGS:
            raise ValueError(f"Inline SVG element <{tag_name}> is not allowed")
        if element.text and element.text.strip() and tag_name not in _SAFE_SVG_TEXT_TAGS:
            raise ValueError(f"Inline SVG element <{tag_name}> must not contain inline text")
        if element.tail and element.tail.strip():
            raise ValueError("Inline SVG must not contain free text nodes")

        for attr_name, attr_value in element.attrib.items():
            if _svg_namespace(attr_name) is not None:
                raise ValueError("Inline SVG must not contain namespaced attributes")
            if attr_name.startswith("on"):
                raise ValueError("Inline SVG event handler attributes are not allowed")
            if attr_name == "style":
                raise ValueError("Inline SVG style attributes are not allowed")
            if attr_name not in _SAFE_SVG_ATTRS:
                raise ValueError(f"Inline SVG attribute '{attr_name}' is not allowed")
            if not _is_safe_svg_attr_value(attr_name, str(attr_value)):
                raise ValueError(f"Inline SVG attribute '{attr_name}' contains an unsafe value")

    ElementTree.register_namespace("", _SAFE_SVG_ROOT_NAMESPACE)
    return ElementTree.tostring(root, encoding="unicode")
