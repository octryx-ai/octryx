"""The Action run's summary message: what each step did, as the run's chat shows it."""

from __future__ import annotations

from typing import Any

# These are imported at module level so tests can patch them cleanly.


def _render_action_summary_message(summary: dict[str, Any]) -> str:
    title = str(summary.get("title") or "Action Summary").strip()
    project_name = str(summary.get("project_name") or "").strip()
    prompt_contract = str(summary.get("prompt_contract") or "").strip()
    primary_model = str(summary.get("primary_model") or "").strip()
    scanned = summary.get("scanned")
    enriched = summary.get("enriched")
    created = summary.get("created")
    updated_count = summary.get("updated")
    skipped = summary.get("skipped")
    lines = [f"{title} completed."]
    if project_name:
        lines.append(f"Project: {project_name}")
    counts = []
    if scanned is not None:
        counts.append(f"scanned {scanned}")
    if enriched is not None:
        counts.append(f"enriched {enriched}")
    if created is not None:
        counts.append(f"created {created}")
    if updated_count is not None:
        counts.append(f"updated {updated_count}")
    if skipped is not None:
        counts.append(f"skipped {skipped}")
    if counts:
        lines.append("Result: " + ", ".join(counts) + ".")
    if primary_model:
        lines.append(f"Primary model: {primary_model}")
    if prompt_contract:
        lines.append(f"Prompt contract: {prompt_contract}")

    entries = summary.get("entries") if isinstance(summary.get("entries"), list) else []
    changed = [
        entry
        for entry in entries
        if isinstance(entry, dict) and str(entry.get("status") or "").strip().lower() in {"created", "updated"}
    ][:5]
    if changed:
        lines.append("")
        lines.append("Changed entries:")
        for entry in changed:
            key = str(entry.get("silver_key") or entry.get("gold_key") or "").strip()
            confidence = entry.get("confidence")
            concepts = ", ".join(str(item) for item in (entry.get("concepts") or [])[:3])
            title_text = str(entry.get("title") or "").strip()
            review_status = str(entry.get("review_status") or "").strip()
            preview = str(entry.get("summary_preview") or "").strip()
            detail = f"- {key}" if key else "- Entry"
            if confidence is not None:
                detail += f" confidence={confidence}"
            if review_status:
                detail += f" review={review_status}"
            if concepts:
                detail += f" concepts={concepts}"
            lines.append(detail)
            if title_text:
                lines.append(f"  Title: {title_text}")
            if preview:
                lines.append(f"  Summary: {preview}")
    return "\n".join(lines).strip()
