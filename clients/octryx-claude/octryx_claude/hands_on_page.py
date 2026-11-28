"""The page side of a hands-on step: a Flutter web app's accessibility tree, finding, scrolling and filling."""

from __future__ import annotations

import time
from typing import Any

TIMEOUT_MS = 15_000
_FIND = """(text) => {
  const want = text.toLowerCase();
  const nodes = Array.from(document.querySelectorAll('flt-semantics, [aria-label], button, a, label, input, '
      + 'textarea, select, [role], h1, h2, h3, h4, p, span, li, td, div'));
  let best = null, bestLen = Infinity;
  for (const e of nodes) {
    const r = e.getBoundingClientRect();
    if (r.width < 1 || r.height < 1) continue;
    const s = getComputedStyle(e);
    if (s.visibility === 'hidden' || s.display === 'none') continue;
    const own = ((e.getAttribute('aria-label') || '') + ' ' + (e.innerText || e.textContent || '')).trim();
    if (!own.toLowerCase().includes(want)) continue;
    if (own.length < bestLen) { best = r; bestLen = own.length; }
  }
  return best ? {x: best.x + best.width / 2, y: best.y + best.height / 2} : null;
}"""
_SEMANTICS = """() => { const p = document.querySelector('flt-semantics-placeholder');
  if (p) { p.click(); return true; } return false; }"""


class StepFailedError(Exception):
    pass


FLUTTER_VIEW = "flt-glass-pane, flutter-view, flt-semantics-placeholder"


def _semantics(page: Any) -> None:
    try:
        page.wait_for_load_state("load", timeout=TIMEOUT_MS)
    except Exception:  # noqa: BLE001 - a slow load is judged by the steps that follow
        return
    if not page.evaluate("() => !!document.querySelector('script[src*=\"flutter\"], flutter-view, flt-glass-pane')"):
        return
    try:
        page.wait_for_selector(FLUTTER_VIEW, state="attached", timeout=TIMEOUT_MS * 2)
        page.wait_for_selector("flt-semantics-placeholder", state="attached", timeout=TIMEOUT_MS)
        page.evaluate(_SEMANTICS)
        page.wait_for_selector("flt-semantics", state="attached", timeout=TIMEOUT_MS)
    except Exception:  # noqa: BLE001 - the steps say what is missing
        pass


def _point(page: Any, text: str, timeout_ms: int = TIMEOUT_MS) -> dict[str, float] | None:
    deadline = time.monotonic() + timeout_ms / 1000
    while True:
        found = page.evaluate(_FIND, text)
        if found or time.monotonic() > deadline:
            return found
        page.wait_for_timeout(250)


SCROLL_STEPS = 8


def _in_view(page: Any, point: dict[str, float]) -> bool:
    # App bars at the top and button bars at the bottom cover the edges of the view.
    size = page.viewport_size or {"width": 1280, "height": 800}
    return 0 <= point["x"] <= size["width"] and size["height"] * 0.15 <= point["y"] <= size["height"] * 0.75


def _reach(page: Any, text: str) -> dict[str, float] | None:
    point = _point(page, text)
    size = page.viewport_size or {"width": 1280, "height": 800}
    center = {"x": size["width"] / 2, "y": size["height"] / 2}
    for direction in (1, -1):
        for _ in range(SCROLL_STEPS):
            if point is not None and _in_view(page, point):
                return point
            page.mouse.move(center["x"], center["y"])
            delta = (point["y"] - center["y"]) if point is not None else direction * size["height"] * 0.6
            page.mouse.wheel(0, delta)
            page.wait_for_timeout(300)
            point = _point(page, text, timeout_ms=0)
    return point


_FIELDS = """() => Array.from(document.querySelectorAll('flt-semantics'))
  .filter(e => e.querySelector('input, textarea')).map(e => e.getBoundingClientRect())
  .filter(r => r.width > 1 && r.height > 1 && r.bottom > 0 && r.top < window.innerHeight)
  .map(r => ({x: r.x + r.width / 2, y: r.y + r.height / 2}))"""


def _in_fields(page: Any, text: str) -> bool:
    want = str(text).casefold()
    return any(want in value.casefold() for value in field_values(page))


def field_values(page: Any) -> list[str]:
    # A Flutter field keeps its value in the DOM only while focused, so each field is focused to read it.
    values: list[str] = []
    for point in page.evaluate(_FIELDS)[:MAX_FIELDS]:
        page.mouse.click(point["x"], point["y"])
        deadline = time.monotonic() + 1.5
        while not page.evaluate(_EDITING_AT, point) and time.monotonic() < deadline:
            page.wait_for_timeout(100)
        if page.evaluate(_EDITING_AT, point):
            values.append(str(page.evaluate(_VALUE) or ""))
        else:
            page.keyboard.press("Escape")
            page.wait_for_timeout(200)
    return values


MAX_FIELDS = 20
# The field at the clicked point has its editing input in focus: Flutter reuses one <input> for the fields it edits,
# so the focused input counts only while its semantics node covers the point.
_EDITING_AT = ("(p) => { const e = document.activeElement; if (!e || !['INPUT', 'TEXTAREA'].includes(e.tagName)) "
               "return false; const n = e.closest('flt-semantics') || e; const r = n.getBoundingClientRect(); "
               "return p.x >= r.left && p.x <= r.right && p.y >= r.top && p.y <= r.bottom; }")
# A label that is its own text above (or left) its field, not the field's own name (a Text over an unlabelled
# field): clicking the text gives the field no focus, so the step clicks the box under the label, as a person does.
# A point already on a field stays as it is.
_FIELD_OF_LABEL = """(p) => {
  const fields = Array.from(document.querySelectorAll('input, textarea')).map(e => e.closest('flt-semantics') || e)
    .map(e => e.getBoundingClientRect()).filter(r => r.width > 1 && r.height > 1);
  if (fields.some(r => p.x >= r.left && p.x <= r.right && p.y >= r.top && p.y <= r.bottom)) return null;
  const near = fields.map(r => {
    const below = r.top >= p.y - 2 && r.top - p.y <= 70 && p.x >= r.left - 8 && p.x <= r.right;
    const right = r.left >= p.x && r.left - p.x <= 320 && p.y >= r.top && p.y <= r.bottom;
    return {r, d: below ? r.top - p.y : right ? r.left - p.x : Infinity};
  }).filter(f => f.d !== Infinity).sort((a, b) => a.d - b.d)[0];
  return near ? {x: near.r.left + Math.min(near.r.width / 2, 40), y: near.r.top + near.r.height / 2} : null;
}"""
# The option of a choice group whose text is the value, nearest under (up to 120 px) or right of its label.
_OPTION_NEAR_LABEL = """(a) => {
  const want = String(a.value).trim().toLowerCase(), p = a.p;
  let best = null, bestD = Infinity;
  for (const e of document.querySelectorAll('flt-semantics, [role], button, label, span, div')) {
    const named = (e.getAttribute('aria-label') || '').trim().toLowerCase();
    const shown = (e.innerText || e.textContent || '').trim().toLowerCase();
    if (named !== want && shown !== want) continue;
    const r = e.getBoundingClientRect();
    if (r.width < 1 || r.height < 1) continue;
    const cx = r.x + r.width / 2, cy = r.y + r.height / 2;
    const below = cy > p.y && cy - p.y <= 120, right = cx > p.x && Math.abs(cy - p.y) <= r.height;
    if (!below && !right) continue;
    const d = Math.hypot(cx - p.x, cy - p.y);
    if (d < bestD) { best = {x: cx, y: cy}; bestD = d; }
  }
  return best;
}"""
_VALUE = "() => { const e = document.activeElement; return e && 'value' in e ? e.value : null; }"
FOCUS_MS = 3000
SETTLE_MS = 300


def _fill(page: Any, label: str, value: str) -> None:
    # Keys typed before Flutter listens are lost; a locator fill never reaches a semantics node.
    field = page.get_by_label(label, exact=False).first
    try:
        editable = field.count() > 0 and field.evaluate(
            "e => ['INPUT', 'TEXTAREA', 'SELECT'].includes(e.tagName) || e.isContentEditable")
    except Exception:  # noqa: BLE001 - a detached or missing node: the Flutter path below decides
        editable = False
    if editable:
        field.fill(value, timeout=4000)
        return
    point = _reach(page, label)
    if point is None:
        raise StepFailedError(f"no field labelled {label!r}")
    field = page.evaluate(_FIELD_OF_LABEL, point)
    if field is None and (option := page.evaluate(_OPTION_NEAR_LABEL, {"p": point, "value": str(value)})):
        # A choice (chips, segments, radio) under its label: a person picks the option, there is no field to focus.
        page.mouse.click(option["x"], option["y"])
        page.wait_for_timeout(SETTLE_MS)
        return
    point = field or point
    page.mouse.click(point["x"], point["y"])
    deadline = time.monotonic() + FOCUS_MS / 1000
    while not page.evaluate(_EDITING_AT, point):
        if time.monotonic() > deadline:
            raise StepFailedError(f"the field labelled {label!r} took no focus")
        page.wait_for_timeout(100)
    # Flutter attaches its key listeners a moment after its input takes focus, and dropped the keys typed after a
    # ControlOrMeta+A shortcut: settle, select the old text in the DOM, type; once more when the value is not there.
    typed = None
    for _attempt in range(2):
        page.wait_for_timeout(SETTLE_MS)
        page.evaluate("() => { const e = document.activeElement; if (e && e.select) { e.select(); } }")
        page.keyboard.type(value)
        page.wait_for_timeout(150)
        typed = page.evaluate(_VALUE)
        if typed is None or str(value) in str(typed):
            return
    raise StepFailedError(f"the field labelled {label!r} shows {typed!r} instead of {value!r}")
