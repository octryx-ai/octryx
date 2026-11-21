"""Build the Engineering Knowledge runtime request from explicit inputs.

A coding migration is known only from an explicit :class:`EngineeringUpgradeTarget` (the selected
upgrade profile, or the structured fields of a request; see :mod:`.runtime_target`). The prompt
text is not an input at all: without a target the request is ``general`` with
``target_source = "not_specified"``, and no Engineering Knowledge Pack context is resolved for it.

A pack build is never a runtime request either: it runs only through its explicit structured
entry points (:mod:`.pack_build_request`).
"""

from __future__ import annotations

from ._runtime_types import (
    TARGET_SOURCE_NOT_SPECIFIED,
    EngineeringKnowledgeRuntimeRequest,
    EngineeringUpgradeTarget,
)


def build_engineering_runtime_request(
    *,
    target: EngineeringUpgradeTarget | None = None,
) -> EngineeringKnowledgeRuntimeRequest:
    if target is None:
        return EngineeringKnowledgeRuntimeRequest(
            intent="general",
            target_source=TARGET_SOURCE_NOT_SPECIFIED,
        )

    target_versions = {key: value for key, value in dict(target.target_versions).items() if value}
    blockers: list[dict[str, str]] = []
    if not target_versions:
        blockers.append(
            {
                "code": "missing_target_versions",
                "message": "Ask for exact target language or framework versions before planning the migration.",
            }
        )
    return EngineeringKnowledgeRuntimeRequest(
        intent="coding_migration",
        stack_key=str(target.stack_key or "").strip(),
        source_versions={key: value for key, value in dict(target.source_versions).items() if value},
        target_versions=target_versions,
        blockers=blockers,
        target_source=target.source,
    )


__all__ = ["build_engineering_runtime_request"]
