"""``documentation.preflight``: everything the publication needs is configured, before card (a) and (b).

``publish_preflight`` and ``needs_configuration``: no configured audience principal
P, no audience semantics or no documentation settings fail **closed** before anything is shown for publication or
written. The run pauses ``needs_configuration``; the requester fixes the configuration and retries the step. Nothing is
created, granted or changed here (configuring them is a person's decision).

The Workspace configures it under its documentation settings (project config ``feature_documentation``):

- ``confluence_space_key`` (and optionally ``parent_page_id``): where the page is published (``page``);
- ``audience_proof``: the named audience — ``semantics`` ``workspace_readers`` (the Workspace boundary only) or
  ``source_restricted`` (needs ``knowledge_source_acl.enforce``), ``principal_user_id`` (P, an active human
  non-admin account other than the requester), ``outsider_user_id`` (O, the outsider-negative probe, neither P nor
  the requester) and ``source_key`` (the Knowledge source that must serve the page);
- ``acceptance_environment`` (optional): ``{name, kind, url}`` of the named preview/test environment the
  functional acceptance (a) is observed on. Without it, (a) cannot be *accepted* (only "not testable yet" or
  rejected), never accepted on an invented environment.

The run's page links the run under the platform's public origin (``platform_public_origin``), so a page published
while (a) is pending can say "acceptance pending as of …" and link the run.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ....models import User, WorkflowRun
from ...project.service import get_project_config
from ..platform.dispatch import FAILED, SUCCEEDED, ToolOutcome
from .page import SETTINGS_KEY, documentation_settings
from .s1_graph import CLASS_NEEDS_CONFIGURATION

SEMANTICS_WORKSPACE_READERS = "workspace_readers"
SEMANTICS_SOURCE_RESTRICTED = "source_restricted"
SEMANTICS = frozenset({SEMANTICS_WORKSPACE_READERS, SEMANTICS_SOURCE_RESTRICTED})
HUMAN_ACCOUNT = "human"


@dataclass(frozen=True, slots=True)
class AudienceSettings:
    semantics: str
    principal_user_id: str
    outsider_user_id: str
    source_key: str

    def to_dict(self) -> dict[str, str]:
        return {"semantics": self.semantics, "principal_user_id": self.principal_user_id,
                "outsider_user_id": self.outsider_user_id, "source_key": self.source_key}


@dataclass(frozen=True, slots=True)
class AcceptanceEnvironment:
    name: str
    kind: str
    url: str

    def to_dict(self) -> dict[str, str]:
        return {"name": self.name, "kind": self.kind, "url": self.url}


def _text(value: Any) -> str:
    return str(value or "").strip()


def audience_settings(project_config: dict[str, Any] | None) -> AudienceSettings | None:
    raw = dict(dict((project_config or {}).get(SETTINGS_KEY) or {}).get("audience_proof") or {})
    if not raw:
        return None
    return AudienceSettings(
        semantics=_text(raw.get("semantics")), principal_user_id=_text(raw.get("principal_user_id")),
        outsider_user_id=_text(raw.get("outsider_user_id")), source_key=_text(raw.get("source_key")))


def acceptance_environment(project_config: dict[str, Any] | None) -> AcceptanceEnvironment | None:
    raw = dict(dict((project_config or {}).get(SETTINGS_KEY) or {}).get("acceptance_environment") or {})
    name, url = _text(raw.get("name")), _text(raw.get("url"))
    if not name:
        return None
    return AcceptanceEnvironment(name=name, kind=_text(raw.get("kind")) or "test",
                                 url=url if url.lower().startswith(("https://", "http://")) else "")


def public_origin() -> str:
    from ....config import get_settings

    origin = _text(get_settings().platform_public_origin).rstrip("/")
    return origin if origin.lower().startswith(("https://", "http://")) else ""


def run_link(run: WorkflowRun) -> str:
    """The run's address under the platform's public origin ('' when the origin is not configured)."""
    origin = public_origin()
    return f"{origin}/api/v1/workflow-runs/{run.id}" if origin else ""


async def _principal_problems(db: AsyncSession, run: WorkflowRun, user_id: str, label: str) -> list[str]:
    from ...admin.governance.admin_access_service import is_global_admin

    if not user_id:
        return [f"no {label} is configured (feature_documentation.audience_proof)"]
    user = await db.get(User, user_id)
    if user is None or not user.is_active:
        return [f"the {label} {user_id} is not an active account"]
    problems = []
    if user.account_type != HUMAN_ACCOUNT:
        problems.append(f"the {label} {user_id} is not a human account")
    if user.id == run.requested_by:
        problems.append(f"the {label} is the requester; the audience proof is never the requester's own search")
    if await is_global_admin(db, user.id):
        problems.append(f"the {label} {user_id} is an admin; an admin is never accepted as the audience")
    return problems


async def configuration_problems(db: AsyncSession, run: WorkflowRun) -> list[str]:
    """What keeps the publication from being configured (empty: ready)."""
    config = await get_project_config(run.project_id, db)
    problems: list[str] = []
    if documentation_settings(config) is None:
        problems.append("the Workspace names no documentation space (feature_documentation.confluence_space_key)")
    audience = audience_settings(config)
    if audience is None:
        return problems + ["no audience is configured (feature_documentation.audience_proof: semantics, principal, "
                           "outsider, source)"]
    if audience.semantics not in SEMANTICS:
        problems.append(f"the audience semantics must be one of: {', '.join(sorted(SEMANTICS))}")
    if audience.semantics == SEMANTICS_SOURCE_RESTRICTED and dict(
            (config or {}).get("knowledge_source_acl") or {}).get("enforce") is not True:
        problems.append("a source-restricted audience needs knowledge_source_acl.enforce")
    if not audience.source_key:
        problems.append("no Knowledge source is named for the audience "
                        "(feature_documentation.audience_proof.source_key)")
    problems += await _principal_problems(db, run, audience.principal_user_id, "audience principal")
    if not audience.outsider_user_id:
        problems.append("no outsider principal is configured for the outsider-negative check")
    elif audience.outsider_user_id == audience.principal_user_id:
        problems.append("the outsider principal must not be the audience principal")
    elif audience.outsider_user_id == run.requested_by:
        problems.append("the outsider principal must not be the requester")
    else:
        problems += await _principal_problems(db, run, audience.outsider_user_id, "outsider principal")
    if not public_origin():
        problems.append("the platform's public origin is not configured (platform_public_origin), so the page "
                        "cannot link the run")
    return problems


async def preflight(db: AsyncSession, run: WorkflowRun) -> ToolOutcome:
    problems = await configuration_problems(db, run)
    if problems:
        return ToolOutcome(FAILED, {"needs_configuration": problems},
                           "the publication is not configured: " + "; ".join(problems)[:450],
                           failure_class=CLASS_NEEDS_CONFIGURATION)
    config = await get_project_config(run.project_id, db)
    audience, environment = audience_settings(config), acceptance_environment(config)
    return ToolOutcome(SUCCEEDED, {"audience": audience.to_dict() if audience else None,
                                   "acceptance_environment": environment.to_dict() if environment else None})


__all__ = ["AcceptanceEnvironment", "AudienceSettings", "acceptance_environment", "audience_settings",
           "configuration_problems", "preflight", "public_origin", "run_link"]
