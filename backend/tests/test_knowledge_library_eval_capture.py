"""Capture records real-shape responses, posts only to the search route and refuses unsafe targets or writing imports."""

from __future__ import annotations

import ast
import json
from pathlib import Path

import httpx
import pytest

from app.services.knowledge.eval import (
    library_case_scores,
    library_cases,
    library_inputs,
    library_inventory,
    library_judgments,
    library_manifest,
    library_records,
    library_run,
    library_scoring,
    library_targets,
)
from app.services.knowledge.eval.library_manifest import load_manifest
from app.services.knowledge.eval.library_run import capture
from app.services.knowledge.eval.library_targets import (
    RefusedTargetError,
    check_base_url,
    check_private_output,
    search_path,
)
from tests.knowledge_library_eval_support import OWN, SHA_A, api_hit, body, case, manifest_doc, record

# --- capture transport -------------------------------------------------------------------------------


def test_a_real_shape_response_round_trips_into_a_bounded_capture_record():
    manifest = load_manifest(manifest_doc(case()))
    long_text = "word " * 200
    response = body([api_hit("rev1:1", text=long_text, workspace="Library", bound=True)])
    result = record(manifest, "C1", response)
    hit = result["hits"][0]
    assert (hit["evidence_key"], hit["source_id"], hit["span_ordinal"], hit["content_sha256"]) == (
        "rev1:1", "src-a", 1, SHA_A)
    assert (hit["workspace"], hit["bound"], hit["relevance_uncalibrated"]) == ("Library", True, 0.4)
    assert len(hit["excerpt"]) <= 200 and len(hit["title"]) <= 120
    assert result["request"] == {"workspace_id": OWN, "mode": "hybrid", "limit": 10,
                                 "query_text": "synthetic question C1", "products": None, "version": None}


def test_capture_only_posts_to_the_search_route_without_retries_redirects_or_leaked_credentials():
    manifest = load_manifest(manifest_doc(case(), case("C2")))
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.method, request.url.path, request.headers.get("authorization")))
        if len(seen) == 2:
            return httpx.Response(302, headers={"location": "https://elsewhere.example/"})
        return httpx.Response(200, json=body([api_hit("rev1:1")]))

    import asyncio

    document = asyncio.run(capture(manifest, base_url="http://127.0.0.1:8000", token="t0ken-value",
                                   transport=httpx.MockTransport(handler)))
    assert seen == [("POST", f"/api/v1/workspaces/{OWN}/knowledge/search", "Bearer t0ken-value")] * 2
    assert [item["response_state"] for item in document["cases"]] == ["ok", "http_error"]
    assert "t0ken-value" not in json.dumps(document)
    assert document["requests_used"] == 2 and document["provider_usage"]["state"] == "unavailable"
    with pytest.raises(RefusedTargetError):
        library_targets._guard(httpx.Request("GET", f"http://127.0.0.1/api/v1/workspaces/{OWN}/knowledge/search"))
    with pytest.raises(RefusedTargetError):
        library_targets._guard(httpx.Request("POST", f"http://127.0.0.1/api/v1/workspaces/{OWN}/knowledge/sources"))


@pytest.mark.parametrize("url", ["http://example.com", "https://user:pw@example.com", "https://example.com/api",
                                 "https://example.com?x=1", "ftp://example.com", "http://10.0.0.5"])
def test_unsafe_targets_are_refused(url):
    with pytest.raises(RefusedTargetError):
        check_base_url(url)


def test_safe_targets_paths_and_private_outputs():
    assert check_base_url("http://localhost:8000") == "http://localhost:8000"
    assert check_base_url("https://octryx.example.com/") == "https://octryx.example.com"
    assert check_base_url("http://[::1]:8000") == "http://[::1]:8000"
    for bad in ("../admin", "a/b", "", "x?y"):
        with pytest.raises(RefusedTargetError):
            search_path(bad)
    with pytest.raises(RefusedTargetError, match="git working tree"):
        check_private_output(Path(__file__).resolve().parent / "capture.json")


def test_the_evaluation_modules_import_nothing_that_writes():
    allowed_internal = {"library_manifest", "library_run", "library_scoring", "golden", "library_inputs",
                        "library_cases", "library_inventory", "library_targets", "library_records",
                        "library_judgments", "library_case_scores"}
    for module in (library_manifest, library_run, library_scoring, library_inputs, library_cases, library_inventory,
                   library_targets, library_records, library_judgments, library_case_scores):
        tree = ast.parse(Path(module.__file__).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.level:
                assert node.module in allowed_internal, (module.__name__, node.module)
            elif isinstance(node, ast.ImportFrom):
                assert node.module.split(".")[0] in {"__future__", "collections", "dataclasses", "datetime",
                                                      "pathlib", "typing", "urllib"}, node.module
            elif isinstance(node, ast.Import):
                assert all(alias.name in {"argparse", "asyncio", "hashlib", "ipaddress", "json", "math", "os", "re",
                                          "sys", "time", "httpx"} for alias in node.names)
