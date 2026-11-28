"""Read-only Library evaluation runner: validate, capture, score.

    python -m app.services.knowledge.eval.library_run validate MANIFEST [--prior-queries FILE ...]
    OCTRYX_EVAL_TOKEN=... python -m app.services.knowledge.eval.library_run capture MANIFEST \\
        --base-url https://host --out /private/dir/capture.json [--prior-queries FILE ...]
    python -m app.services.knowledge.eval.library_run score MANIFEST CAPTURE --out REPORT \\
        [--judgments FILE] [--inventory FILE] [--prior-queries FILE ...]

``capture`` is the only step that talks to a server, and only through the normal authenticated search route:
one sequential ``POST /api/v1/workspaces/{id}/knowledge/search`` per case. Requests run at concurrency 1, with
no retries, no redirects and a per-request timeout. The request count is checked against the frozen budget
before the first request. The bearer token comes from ``OCTRYX_EVAL_TOKEN`` only; neither it, any header, an
error body nor the environment is printed or stored. Real captures hold source content (titles, excerpts),
so they are never written into a git working tree: root reviews and redacts them before any publication.

This module never embeds, ingests, projects, indexes or writes evidence. It reads no settings.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from .library_inputs import Case, EvaluationInputError, Manifest, canonical_sha256, load_json
from .library_manifest import load_manifest
from .library_records import capture_record
from .library_targets import (
    CAPTURE_SCHEMA,
    PROVIDER_USAGE,
    TOKEN_ENV,
    RefusedTargetError,
    _guard,
    check_base_url,
    check_private_output,
    search_path,
)


def _now() -> str:
    return datetime.now(UTC).isoformat()


async def _capture_case(client: httpx.AsyncClient, case: Case, project_id: str, path: str, token: str):
    payload: dict[str, Any] = {"query_text": case.query, "limit": case.limit, "mode": case.mode}
    if case.products is not None:
        payload["products"] = list(case.products)
    if case.version is not None:
        payload["version"] = case.version
    started = time.perf_counter()
    try:
        response = await client.post(
            path, json=payload, headers={"Authorization": f"Bearer {token}"}
        )
        elapsed = (time.perf_counter() - started) * 1000
        try:
            body = response.json()
        except ValueError:
            body = None
        return capture_record(case, project_id, status=response.status_code, body=body, latency_ms=elapsed)
    except httpx.HTTPError as error:
        elapsed = (time.perf_counter() - started) * 1000
        return capture_record(case, project_id, status=None, body=None, latency_ms=elapsed,
                              failure=type(error).__name__)


async def capture(manifest: Manifest, *, base_url: str, token: str, transport: httpx.AsyncBaseTransport | None = None):
    base = check_base_url(base_url)
    if not token or any(char.isspace() for char in token):
        raise RefusedTargetError(f"{TOKEN_ENV} must hold one bearer token")
    budget = manifest.budget
    if len(manifest.cases) > budget["max_search_requests"]:
        raise RefusedTargetError("the cases exceed the search request budget")
    paths = {case.id: search_path(manifest.workspaces[case.workspace]) for case in manifest.cases}
    started_at = _now()
    records: list[dict[str, Any]] = []
    async with httpx.AsyncClient(
        base_url=base,
        transport=transport or httpx.AsyncHTTPTransport(retries=0),
        timeout=httpx.Timeout(budget["timeout_s"]),
        follow_redirects=False,
        event_hooks={"request": [_async_guard]},
        trust_env=False,
    ) as client:
        for case in manifest.cases:
            project_id = manifest.workspaces[case.workspace]
            records.append(await _capture_case(client, case, project_id, paths[case.id], token))
            client.cookies.clear()
    return {
        "schema": CAPTURE_SCHEMA,
        "manifest_sha256": manifest.sha256,
        "started_at": started_at,
        "finished_at": _now(),
        "declarations": {
            "principal": manifest.raw["principal"],
            "environment": manifest.raw["environment_declared"],
            "verified": False,
        },
        "budget": dict(budget),
        "transport": {"redirects": "disabled", "retries": 0, "concurrency": 1, "timeout_s": budget["timeout_s"]},
        "requests_used": len(records),
        "logical_provider_estimate": manifest.logical_provider_estimate,
        "provider_usage": dict(PROVIDER_USAGE),
        "cases": records,
    }


async def _async_guard(request: httpx.Request) -> None:
    _guard(request)


def _write(path: Path, document: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document, indent=1, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("validate", "capture", "score"):
        command = commands.add_parser(name)
        command.add_argument("manifest")
        command.add_argument("--prior-queries", action="append", default=[])
        if name == "capture":
            command.add_argument("--base-url", required=True)
            command.add_argument("--out", required=True)
        if name == "score":
            command.add_argument("capture")
            command.add_argument("--judgments")
            command.add_argument("--inventory")
            command.add_argument("--out", required=True)
    args = parser.parse_args(argv)
    try:
        manifest = load_manifest(load_json(args.manifest), prior_query_paths=args.prior_queries or None)
        if args.command == "validate":
            print(json.dumps({
                "valid": True,
                "manifest_sha256": manifest.sha256,
                "cases": len(manifest.cases),
                "logical_provider_estimate": manifest.logical_provider_estimate,
                "overlap_check": manifest.overlap_check,
            }, indent=1))
            return 0
        if args.command == "capture":
            out = check_private_output(args.out)
            document = asyncio.run(
                capture(manifest, base_url=args.base_url, token=os.environ.get(TOKEN_ENV, "").strip())
            )
            _write(out, document)
            states = [record["response_state"] for record in document["cases"]]
            print(json.dumps({"requests_used": document["requests_used"], "capture_sha256": canonical_sha256(document),
                              "response_states": {state: states.count(state) for state in sorted(set(states))}}))
            return 0
        from .library_scoring import score_documents

        report = score_documents(
            manifest,
            load_json(args.capture),
            load_json(args.judgments) if args.judgments else None,
            load_json(args.inventory) if args.inventory else None,
        )
        _write(Path(args.out), report)
        print(json.dumps({"status": report["status"], "problems": report.get("problems", [])}))
        return 0 if report["status"] == "scored" else 2
    except (EvaluationInputError, RefusedTargetError, ValueError, OSError) as error:
        print(json.dumps({"refused": str(error)}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
