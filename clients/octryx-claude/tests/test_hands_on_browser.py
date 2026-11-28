"""The hands-on browser acts like a person: it scrolls to a target, fills a labelled field and picks a choice."""

from __future__ import annotations

import pytest

from tests.hands_on_support import _port, needs_chrome


@needs_chrome
def test_a_click_target_below_the_fold_is_scrolled_to(tmp_path):
    pytest.importorskip("playwright")
    import http.server
    import threading

    from playwright.sync_api import sync_playwright

    from octryx_claude.hands_on_browser import run_scenario

    (tmp_path / "index.html").write_text(
        "<html><body><div style='height:3000px'>top</div>"
        "<button onclick=\"document.getElementById('o').textContent='clicked'\">Deep button</button>"
        "<p id='o'></p></body></html>")
    port = _port()
    handler = lambda *args: http.server.SimpleHTTPRequestHandler(*args, directory=str(tmp_path))  # noqa: E731
    server = http.server.HTTPServer(("127.0.0.1", port), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    scenario = {"id": "S1", "viewport": {"width": 390, "height": 600}, "fresh_profile": True, "seed": [],
                "steps": [{"do": "goto", "path": "/"}, {"do": "click", "text": "Deep button"},
                          {"do": "expect_text", "text": "clicked"}]}
    try:
        with sync_playwright() as playwright:
            result = run_scenario(playwright, "chrome", scenario, f"http://127.0.0.1:{port}", tmp_path)
    finally:
        server.shutdown()
        server.server_close()
    assert result["passed"] is True, result


def test_a_field_whose_label_is_its_own_text_above_it_is_filled_by_clicking_the_box(tmp_path):
    pytest.importorskip("playwright")
    import http.server
    import threading

    from playwright.sync_api import sync_playwright

    from octryx_claude.hands_on_browser import run_scenario

    (tmp_path / "index.html").write_text(
        "<html><body style='margin:200px 40px'><section><flt-semantics style='display:block;"
        "height:20px;width:40px'>Name</flt-semantics>"
        "<flt-semantics style='display:block;margin-top:8px;height:40px;width:300px'>"
        "<input style='width:280px;height:36px' "
        "oninput=\"document.getElementById('o').textContent='typed '+this.value\">"
        "</flt-semantics></section><p id='o'></p></body></html>")
    port = _port()
    handler = lambda *args: http.server.SimpleHTTPRequestHandler(*args, directory=str(tmp_path))  # noqa: E731
    server = http.server.HTTPServer(("127.0.0.1", port), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    scenario = {"id": "S1", "viewport": {"width": 800, "height": 600}, "fresh_profile": True, "seed": [],
                "steps": [{"do": "goto", "path": "/"}, {"do": "fill", "label": "Name", "value": "M1"},
                          {"do": "expect_text", "text": "typed M1"}]}
    try:
        with sync_playwright() as playwright:
            result = run_scenario(playwright, "chrome", scenario, f"http://127.0.0.1:{port}", tmp_path)
    finally:
        server.shutdown()
        server.server_close()
    assert result["passed"] is True, result.get("error")


def test_a_fill_on_a_choice_group_picks_the_option_like_a_person(tmp_path):
    pytest.importorskip("playwright")
    import http.server
    import threading

    from playwright.sync_api import sync_playwright

    from octryx_claude.hands_on_browser import run_scenario

    (tmp_path / "index.html").write_text(
        "<html><body style='margin:200px 40px'><section>"
        "<flt-semantics style='display:block;height:20px;width:90px'>Roast level</flt-semantics>"
        "<flt-semantics role='button' style='display:inline-block;margin:8px'>Light</flt-semantics>"
        "<flt-semantics role='button' style='display:inline-block;margin:8px' "
        "onclick=\"document.getElementById('o').textContent='picked medium'\">Medium</flt-semantics>"
        "</section><p id='o'></p></body></html>")
    port = _port()
    handler = lambda *args: http.server.SimpleHTTPRequestHandler(*args, directory=str(tmp_path))  # noqa: E731
    server = http.server.HTTPServer(("127.0.0.1", port), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    scenario = {"id": "S1", "viewport": {"width": 800, "height": 600}, "fresh_profile": True, "seed": [],
                "steps": [{"do": "goto", "path": "/"}, {"do": "fill", "label": "Roast level", "value": "Medium"},
                          {"do": "expect_text", "text": "picked medium"}]}
    try:
        with sync_playwright() as playwright:
            result = run_scenario(playwright, "chrome", scenario, f"http://127.0.0.1:{port}", tmp_path)
    finally:
        server.shutdown()
        server.server_close()
    assert result["passed"] is True, result.get("error")
