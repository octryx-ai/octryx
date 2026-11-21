"""Constants for Office template package extraction."""

from __future__ import annotations

OFFICE_TEMPLATE_SUFFIXES = {".potx": "pptx", ".dotx": "docx", ".xltx": "xlsx"}
VECTOR_ASSET_SUFFIXES = {".svg", ".emf", ".wmf"}
RASTER_ASSET_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".tif", ".tiff", ".wdp"}
XML_NS = {
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
    "p": "http://schemas.openxmlformats.org/presentationml/2006/main",
}
NS_P = XML_NS["p"]
NS_A = XML_NS["a"]
NS_R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
NS_PKG = "http://schemas.openxmlformats.org/package/2006/relationships"
NS_SVG = "http://schemas.microsoft.com/office/drawing/2016/SVG/main"
SVG_NS = {"svg": "http://www.w3.org/2000/svg"}
EMU_PER_INCH = 914400
