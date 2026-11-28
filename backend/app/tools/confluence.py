"""Confluence Server/Data Center tool implementations with space/page allowlists."""

import hashlib
import logging
import re
from typing import Any

import httpx

from ..services.ai_marking import CONFLUENCE_LABEL, MARKER_PREFIX
from ..services.request_analysis import effective_limit_from_request_analysis
from ._confluence_access import (
    ancestor_ids_of,
    complete_ancestor_ids,
    confluence_auth_headers,
    confluence_client,
    normalize_space_rules,
    page_allowed,
    space_allowed,
)
from ._confluence_descendants import fetch_child_page_summaries
from ._confluence_evidence import page_url, page_webui, with_page_source
from ._confluence_instance import confluence_instance, connection_refusal, instance_refusal
from ._confluence_listing import effective_confluence_timeout, list_confluence_pages
from ._confluence_page_lookup import extract_page_metadata, fetch_page_record
from ._confluence_storage import normalize_storage_content
from ._confluence_write import build_add_comment_payload, build_create_page_payload, build_update_page_payload
from .context import ToolContext
from .empty_search_hint import with_empty_search_hint
from .evidence_fields import source_fields, with_source

MAX_CONTENT_CHARS = 12000

logger = logging.getLogger(__name__)


def _truncate(text: str) -> str:
    if len(text) <= MAX_CONTENT_CHARS:
        return text
    return text[:MAX_CONTENT_CHARS] + "\n...[truncated]"


def _split_cql_order_by(cql: str) -> tuple[str, str]:
    text = str(cql or "").strip()
    match = re.search(r"\border\s+by\b", text, flags=re.IGNORECASE)
    if not match:
        return text, ""
    return text[: match.start()].strip(), text[match.start() :].strip()


def _confluence_user_summary(user: Any) -> dict[str, Any] | None:
    if not isinstance(user, dict):
        return None
    name = str(user.get("username") or user.get("name") or user.get("userKey") or "").strip()
    display_name = str(user.get("displayName") or "").strip()
    email = str(user.get("email") or user.get("emailAddress") or "").strip()
    if not any((name, display_name, email)):
        return None
    return {
        "name": name or None,
        "display_name": display_name or None,
        "email": email or None,
    }


def _parent_of(ancestor_ids: list[str] | None) -> str | None:
    if ancestor_ids is None:
        return None
    return ancestor_ids[-1] if ancestor_ids else ""


def storage_sha256(storage: str) -> str:
    return hashlib.sha256(str(storage or "").encode("utf-8")).hexdigest()


def _written_storage(sent: str, result: dict[str, Any]) -> dict[str, Any]:
    stored = ((result.get("body") or {}).get("storage") or {}).get("value")
    return {"sent_storage_sha256": storage_sha256(sent),
            **({"storage_sha256": storage_sha256(stored)} if isinstance(stored, str) else {})}


def _confluence_page_search_summary(page: dict[str, Any], confluence_url: str) -> dict[str, Any]:
    pid = str(page.get("id") or "")
    version = page.get("version") or {}
    # The page's canonical link (as Source Sync stores it), also its citable source.
    url = page_url(confluence_url, pid, webui=page_webui(page))
    summary = {
        "id": pid,
        "title": page.get("title"),
        "space_key": (page.get("space") or {}).get("key", ""),
        "version": version.get("number"),
        "updated_by": _confluence_user_summary(version.get("by")),
        "updated_when": version.get("when"),
        "url": url,
    }
    return with_source(summary, title=page.get("title") or pid, url=url)


def _confluence_child_summary(page: dict[str, Any], confluence_url: str) -> dict[str, Any]:
    version = page.get("version") or {}
    summary = {
        "id": str(page.get("id") or ""),
        "title": page.get("title"),
        "space_key": (page.get("space") or {}).get("key", ""),
        "version": version.get("number"),
        "updated_by": _confluence_user_summary(version.get("by")),
        "updated_when": version.get("when"),
    }
    return with_page_source(summary, confluence_url, webui=page_webui(page))


class ListConfluencePages:
    name = "list_confluence_pages"
    description = "List Confluence pages explicitly allowed for the current project, or browse allowed spaces."

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        listed = await list_confluence_pages(params, context)
        pages = listed.get("pages")
        if isinstance(pages, list):
            # Each listed page names its viewpage link on the configured Confluence (evidence fields).
            confluence_url = str(context.project_config.get("confluence_url") or "").strip().rstrip("/")
            listed["pages"] = [
                with_page_source(page, confluence_url) if isinstance(page, dict) else page for page in pages
            ]
        return listed


class GetConfluencePage:
    name = "get_confluence_page"
    description = "Read a Confluence page by id or title, restricted by configured spaces/pages."

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        confluence_url = str(context.project_config.get("confluence_url") or "").strip().rstrip("/")
        if not confluence_url:
            return {"error": "No Confluence URL configured for this project"}
        if refused := instance_refusal(params, confluence_url) or connection_refusal(params, context):
            return refused  # bound to the confirmed instance and connection, before any request

        page_id = str(params.get("page_id") or "").strip()
        title = str(params.get("title") or "").strip()
        space_key = str(params.get("space_key") or "").strip()
        if page_id and not page_id.isdigit() and not title:
            # Models occasionally place the page title into `page_id`. Treat that value as the title
            # instead of hard-failing.
            title = page_id
            page_id = ""
        if not page_id and not title:
            return {"error": "page_id or title is required"}

        headers = {"Accept": "application/json", **confluence_auth_headers(context)}
        request_kwargs = {"headers": headers}

        timeout = effective_confluence_timeout(context, params)
        async with httpx.AsyncClient(**confluence_client(context, timeout)) as client:
            page = await fetch_page_record(
                client,
                confluence_url,
                request_kwargs,
                page_id=page_id if page_id.isdigit() else "",
                title=title,
                space_key=space_key,
                expand="body.storage,space,version,history,ancestors",
            )
        if not page:
            # Structured: the API answered and found nothing (a failure raises instead). Only this lets a publisher
            # treat a title as free.
            # ``lookup: title``: a page-id read never lands here (its 404 raises), nor does a route/space failure.
            return {"error": "Confluence page not found", "status_code": 404, "not_found": True, "lookup": "title",
                    "instance": confluence_instance(confluence_url)}

        page_metadata = extract_page_metadata(
            page,
            fallback_page_id=page_id,
            fallback_title=title,
            fallback_space_key=space_key,
        )
        if not page_allowed(
            context,
            page_id=page_metadata["resolved_id"],
            space_key=page_metadata["resolved_space"],
            ancestor_ids=page_metadata["ancestor_ids"],
        ):
            return {
                "error": "Confluence page "
                f"{page_metadata['resolved_title'] or page_metadata['resolved_id']} "
                "is not allowed for this project"
            }
        url = page_url(confluence_url, page_metadata["resolved_id"], webui=page_metadata.get("webui"))
        source = source_fields(title=page_metadata["resolved_title"], url=url) if url else {}
        return {
            "id": page_metadata["resolved_id"],
            "title": page_metadata["resolved_title"],
            # The page's canonical link on the configured Confluence (evidence fields).
            "url": url,
            **source,
            "space_key": page_metadata["resolved_space"],
            "version": page_metadata["version"],
            # The full storage body's hash and length (``content`` below is truncated): a caller proves what the
            # page holds without the prompt projection's cut (documentation publish read-back).
            "storage_sha256": storage_sha256(page_metadata["body"]),
            "instance": confluence_instance(confluence_url),
            # The page's actual location: its direct parent ("" at the space root, None when the answer
            # carried no ancestors).
            "parent_id": _parent_of(complete_ancestor_ids(page)),
            "storage_length": len(str(page_metadata["body"] or "")),
            "created_by": _confluence_user_summary(page_metadata.get("created_by")),
            "created_when": page_metadata.get("created_when"),
            "updated_by": _confluence_user_summary(page_metadata.get("updated_by")),
            "updated_when": page_metadata.get("updated_when"),
            "content": _truncate(page_metadata["body"]),
        }


# ---------------------------------------------------------------------------
# Write helpers
# ---------------------------------------------------------------------------


def _request_kwargs(context: ToolContext) -> dict:
    headers = {"Accept": "application/json", "Content-Type": "application/json", **confluence_auth_headers(context)}
    kwargs: dict[str, Any] = {"headers": headers}
    return kwargs


async def _add_ai_label(client: httpx.AsyncClient, confluence_url: str, page_id: str, kwargs: dict) -> None:
    if not page_id:
        return
    try:
        response = await client.post(f"{confluence_url}/rest/api/content/{page_id}/label",
                                     json=[{"prefix": "global", "name": CONFLUENCE_LABEL}], **kwargs)
        response.raise_for_status()
    except Exception:  # noqa: BLE001 - the label never fails the write
        logger.warning("confluence: could not add the %s label to page %s", CONFLUENCE_LABEL, page_id,
                       exc_info=True)


class SearchConfluence:
    name = "search_confluence"
    description = (
        "Search Confluence pages by full text or CQL query. Results are restricted to configured allowed spaces/pages."
    )

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        confluence_url = str(context.project_config.get("confluence_url") or "").strip().rstrip("/")
        if not confluence_url:
            return {"error": "No Confluence URL configured for this project"}

        query = str(params.get("query") or "").strip()
        cql = str(params.get("cql") or "").strip()
        space_key = str(params.get("space_key") or "").strip()
        include_child_summary = bool(params.get("include_child_summary") or params.get("include_children_summary"))
        child_limit = max(0, min(int(params.get("child_limit") or 5), 20))
        limit = effective_limit_from_request_analysis(
            snapshot=context.turn_context_snapshot,
            fallback_user_message=context.current_user_message,
            requested_limit=params.get("limit"),
            default_if_unspecified=100,
            hard_max=250,
        )

        if not query and not cql:
            return {"error": "query or cql is required"}

        # Build CQL
        if not cql:
            escaped = query.replace('"', '\\"')
            cql_parts = [f'text ~ "{escaped}"']
            space_rules = [r for r in normalize_space_rules(context.project_config) if r.get("enabled", True)]
            if space_key:
                if not space_allowed(context, space_key):
                    return {"error": f"Space '{space_key}' is not allowed for this project"}
                cql_parts.append(f'space = "{space_key}"')
            elif space_rules:
                keys = ", ".join(f'"{r["space_key"]}"' for r in space_rules)
                cql_parts.append(f"space in ({keys})")
            cql_parts.append('type = "page"')
            cql = " AND ".join(cql_parts) + " ORDER BY lastmodified DESC"
        else:
            # Inject space restriction into explicit CQL if spaces configured
            space_rules = [r for r in normalize_space_rules(context.project_config) if r.get("enabled", True)]
            if space_rules and "space" not in cql.lower():
                keys = ", ".join(f'"{r["space_key"]}"' for r in space_rules)
                base_cql, order_by = _split_cql_order_by(cql)
                cql = f"space in ({keys}) AND ({base_cql})"
                if order_by:
                    cql = f"{cql} {order_by}"

        kwargs = _request_kwargs(context)
        results = []
        timeout = effective_confluence_timeout(context, params)
        async with httpx.AsyncClient(**confluence_client(context, timeout)) as client:
            response = await client.get(
                f"{confluence_url}/rest/api/content/search",
                # Ancestors: a page below an allowed subtree (and not below one of its excludes) is a result.
                params={"cql": cql, "limit": limit, "expand": "space,version,ancestors"},
                **kwargs,
            )
            response.raise_for_status()
            payload = response.json()

            ancestors_by_id: dict[str, list[str]] = {}
            for page in payload.get("results", []):
                pid = str(page.get("id") or "")
                pspace = (page.get("space") or {}).get("key", "")
                ancestors = ancestor_ids_of(page)
                if page_allowed(context, page_id=pid, space_key=pspace, ancestor_ids=ancestors):
                    if ancestors is not None:
                        ancestors_by_id[pid] = ancestors
                    results.append(_confluence_page_search_summary(page, confluence_url))

            if include_child_summary and child_limit > 0:
                for item in results:
                    page_id = str(item.get("id") or "").strip()
                    if not page_id:
                        continue
                    try:
                        child_pages, child_complete = await fetch_child_page_summaries(
                            client,
                            confluence_url,
                            kwargs,
                            page_id=page_id,
                            limit=child_limit,
                            include_versions=True,
                        )
                    except httpx.HTTPStatusError:
                        item["child_lookup_error"] = "Confluence child page lookup failed"
                        continue
                    allowed_children = []
                    # A child's path is its parent's path and the parent (unknown while the parent's is).
                    parent_ancestors = ancestors_by_id.get(page_id)
                    child_ancestors = None if parent_ancestors is None else [*parent_ancestors, page_id]
                    for child_page in child_pages:
                        child_space = (child_page.get("space") or {}).get("key") or str(
                            item.get("space_key") or ""
                        )
                        if page_allowed(
                            context,
                            page_id=str(child_page.get("id") or ""),
                            space_key=child_space,
                            ancestor_ids=child_ancestors,
                        ):
                            allowed_children.append(_confluence_child_summary(child_page, confluence_url))
                    item["child_count"] = len(allowed_children)
                    item["child_listing_complete"] = child_complete
                    item["children"] = allowed_children

        return with_empty_search_hint({"cql": cql, "total": len(results), "results": results})


class CreateConfluencePage:
    name = "create_confluence_page"
    description = (
        "Create a new Confluence page in an allowed space. "
        "Content should be Confluence Storage Format (HTML-like) or plain text."
    )

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        confluence_url = str(context.project_config.get("confluence_url") or "").strip().rstrip("/")
        if not confluence_url:
            return {"error": "No Confluence URL configured for this project"}
        if refused := instance_refusal(params, confluence_url) or connection_refusal(params, context):
            return refused  # bound to the confirmed instance and connection, before any request

        space_key = str(params.get("space_key") or "").strip().upper()
        title = str(params.get("title") or "").strip()
        content = str(params.get("content") or "").strip()
        if not space_key or not title:
            return {"error": "space_key and title are required"}
        if not space_allowed(context, space_key):
            return {"error": f"Space '{space_key}' is not allowed for this project"}

        parent_id = str(params.get("parent_id") or "").strip() or None
        storage_content = normalize_storage_content(content)

        payload = build_create_page_payload(
            space_key=space_key,
            title=title,
            storage_content=storage_content,
            parent_id=parent_id,
        )

        kwargs = _request_kwargs(context)
        async with httpx.AsyncClient(**confluence_client(context, 30)) as client:
            response = await client.post(
                f"{confluence_url}/rest/api/content",
                json=payload,
                **kwargs,
            )
            response.raise_for_status()
            result = response.json()
            if MARKER_PREFIX in storage_content:
                await _add_ai_label(client, confluence_url, str(result.get("id") or ""), kwargs)

        return {
            "id": result.get("id"),
            "title": result.get("title"),
            "space_key": space_key,
            "version": 1,
            "url": f"{confluence_url}/pages/{result.get('id')}",
            "status": "created",
            "instance": confluence_instance(confluence_url),
            **_written_storage(storage_content, result),
        }


class UpdateConfluencePage:
    name = "update_confluence_page"
    description = (
        "Update an existing Confluence page. Provide either page_id or title+space_key. "
        "The new content replaces the current body. "
        "Content should be Confluence Storage Format or plain text."
    )

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        confluence_url = str(context.project_config.get("confluence_url") or "").strip().rstrip("/")
        if not confluence_url:
            return {"error": "No Confluence URL configured for this project"}
        if refused := instance_refusal(params, confluence_url) or connection_refusal(params, context):
            return refused  # bound to the confirmed instance and connection, before any request

        page_id = str(params.get("page_id") or "").strip()
        title = str(params.get("title") or "").strip()
        space_key = str(params.get("space_key") or "").strip()
        new_content = str(params.get("content") or "").strip()
        new_title = str(params.get("new_title") or "").strip()

        if not page_id and not title:
            return {"error": "page_id or title is required"}
        if not new_content and not new_title:
            return {"error": "content or new_title is required"}

        kwargs = _request_kwargs(context)
        async with httpx.AsyncClient(**confluence_client(context, 30)) as client:
            page = await fetch_page_record(
                client,
                confluence_url,
                kwargs,
                page_id=page_id,
                title=title,
                space_key=space_key,
                expand="body.storage,space,version,history,ancestors",
            )
            if not page:
                return {"error": "Page not found"}

            page_metadata = extract_page_metadata(
                page,
                fallback_page_id=page_id,
                fallback_title=title,
                fallback_space_key=space_key,
            )
            resolved_id = page_metadata["resolved_id"]
            resolved_title = new_title or page_metadata["resolved_title"]
            resolved_space = page_metadata["resolved_space"]
            current_version = page_metadata["version"] or 1

            if not page_allowed(
                context,
                page_id=resolved_id,
                space_key=resolved_space,
                ancestor_ids=page_metadata["ancestor_ids"],
            ):
                return {"error": f"Page '{resolved_title}' is not allowed for this project"}

            # Compare-and-set: with ``expected_version`` the update applies only to that version, and the PUT
            # names expected + 1, so Confluence refuses a concurrent edit instead of it being overwritten.
            expected_version = params.get("expected_version")
            if expected_version is not None:
                try:
                    expected_version = int(expected_version)
                except (TypeError, ValueError):
                    return {"error": "expected_version must be a version number"}
                if int(current_version) != expected_version:
                    return {"error": f"version_conflict: page {resolved_id} is at version {current_version}, "
                                     f"not {expected_version}", "status_code": 409, "current_version": current_version}

            # Prepare updated content
            # Only new content is agent output: a title-only update keeps the stored body (and is not marked).
            storage_content = normalize_storage_content(new_content) if new_content else page_metadata["body"]

            update_payload = build_update_page_payload(
                title=resolved_title,
                version_number=(expected_version if expected_version is not None else current_version) + 1,
                storage_content=storage_content,
            )

            update_resp = await client.put(
                f"{confluence_url}/rest/api/content/{resolved_id}",
                json=update_payload,
                **kwargs,
            )
            update_resp.raise_for_status()
            result = update_resp.json()
            if new_content and MARKER_PREFIX in storage_content:
                await _add_ai_label(client, confluence_url, resolved_id, kwargs)

        return {
            "id": resolved_id,
            "title": resolved_title,
            "space_key": resolved_space,
            "version": (result.get("version") or {}).get("number"),
            "status": "updated",
            "instance": confluence_instance(confluence_url),
            **_written_storage(storage_content, result),
        }


class AddConfluenceComment:
    name = "add_confluence_comment"
    description = "Add a comment to a Confluence page."

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        confluence_url = str(context.project_config.get("confluence_url") or "").strip().rstrip("/")
        if not confluence_url:
            return {"error": "No Confluence URL configured for this project"}

        page_id = str(params.get("page_id") or "").strip()
        body = str(params.get("body") or "").strip()
        if not page_id or not body:
            return {"error": "page_id and body are required"}

        # Check page is allowed — fetch space key first
        kwargs = _request_kwargs(context)
        async with httpx.AsyncClient(**confluence_client(context, 30)) as client:
            page = await fetch_page_record(
                client,
                confluence_url,
                kwargs,
                page_id=page_id,
                title="",
                space_key="",
                expand="space,history,version,ancestors",
            )
            page_metadata = extract_page_metadata(page, fallback_page_id=page_id)
            if not page_allowed(
                context,
                page_id=page_id,
                space_key=page_metadata["resolved_space"],
                ancestor_ids=page_metadata["ancestor_ids"],
            ):
                return {"error": f"Page '{page_metadata['resolved_title']}' is not allowed for this project"}

            # Post comment
            comment_payload = build_add_comment_payload(
                page_id=page_id,
                storage_content=normalize_storage_content(body),
            )
            post_resp = await client.post(
                f"{confluence_url}/rest/api/content",
                json=comment_payload,
                **kwargs,
            )
            post_resp.raise_for_status()
            result = post_resp.json()

        return {
            "comment_id": result.get("id"),
            "page_id": page_id,
            "status": "comment_added",
        }
