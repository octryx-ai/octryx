from __future__ import annotations

from tests.guards._legacy_words._build import concept, within

VENDOR_TEXT = concept(
    "'deprecated' quoted from a vendor: a provider's error text the platform recognises, or a vendor environment "
    "variable the launcher documents",
    *within("backend/app/services/model_gateway/litellm/chat_contract.py", "chat_payload",
            '# but their default ("`temperature` is deprecated for this model" / "Only temperature=1 is '
            'supported").'),
    *within("clients/octryx-claude/README.md", "<module>",
            "| `ANTHROPIC_MODEL`, `ANTHROPIC_DEFAULT_{SONNET,OPUS,HAIKU}_MODEL` and `CLAUDE_CODE_SUBAGENT_MODEL` "
            "are supported. `ANTHROPIC_SMALL_FAST_MODEL` is deprecated: `ANTHROPIC_DEFAULT_HAIKU_MODEL` also "
            "covers background tasks | https://code.claude.com/docs/en/env-vars , "
            "https://code.claude.com/docs/en/model-config |"),
)


EXTERNAL_FORMAT = concept(
    "'legacy' naming an outside format or API: binary Office formats, IPv4 short forms, Confluence's v1 "
    "legacy-view body, ServiceNow roles, older Bedrock model generations",
    *within("backend/app/services/knowledge/endpoint_rules.py", "is_valid_host",
            '# A numeric last label is how resolvers accept legacy IPv4 forms ("127.1").'),
    *within("backend/app/services/knowledge/ingestion/media_types.py", "<module>",
            'b"\\xd0\\xcf\\x11\\xe0", # legacy OLE compound file: doc, xls, ppt'),
    *within("backend/app/services/knowledge/sources/sync/confluence_pinned.py", "<module>",
            '"""The pinned source read of one published page: the legacy-view profile, its refusals and its '
            'document."""',
            '"id": "confluence-cloud-legacy-view@2026-10-13",'),
    *within("backend/app/services/office/documents.py", "<module>",
            "#: OOXML only: legacy binary formats (.doc/.xls/.ppt) are neither read by the engine nor rendered."),
    *within("backend/app/services/office/render_sandbox.py", "<module>",
            "#: OOXML only: the legacy binary import filters (.doc/.xls/.ppt) are not exposed to user files."),
    *within("backend/app/services/workflow_runs/documentation/knowledge.py", "_pinned_refusal",
            'return CLASS_PARSE_FAILED, "the legacy view read is unavailable for this page (profile removal " \\',
            'return CLASS_PARSE_FAILED, "the pinned read answered outside the legacy-view profile", facts'),
)


CUSTOMER_LEGACY_FILES = concept(
    "'legacy': files of a customer repository that predate its code style (touched legacy files only warn)",
)
