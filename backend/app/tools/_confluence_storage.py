"""Internal helpers for Confluence storage-format payloads."""


def normalize_storage_content(content: str) -> str:
    """Wrap plain text in a storage paragraph and preserve existing storage markup."""
    text = str(content or "").strip()
    if text and "<" not in text:
        escaped = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        return f"<p>{escaped}</p>"
    return text
