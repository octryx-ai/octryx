"""The configured audience principals: settings, the preflight refusal and the account/role/ACL snapshot."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from sqlalchemy.ext.asyncio import AsyncSession

from ....models import Project, User, WorkflowRun
from ...access_control import _user_is_admin, get_project_role_for_user
from ...project.service import get_project_config
from .audience_contract import (
    AUDIENCE_CONFIG_PATH,
    AUDIENCE_KEY,
    AUTHOR_ROLES,
    CODE_NEEDS_CONFIGURATION,
    CODE_PRINCIPAL,
    DEFAULT_TTL_HOURS,
    MAX_TTL_HOURS,
    ROLE_AUDIENCE,
    ROLE_OUTSIDER,
    SEMANTICS,
    SEMANTICS_SOURCE,
    SEMANTICS_WORKSPACE,
    AudienceProofError,
)
from .knowledge_proof import CLASS_NEEDS_CONFIGURATION
from .page import SETTINGS_KEY

if TYPE_CHECKING:
    from .audience_publication import ConfirmedPublication


@dataclass(frozen=True, slots=True)
class AudienceSettings:
    semantics: str
    principal_user_id: str
    outsider_user_id: str
    ttl_hours: int

    def principal_for(self, role: str) -> str:
        return self.principal_user_id if role == ROLE_AUDIENCE else self.outsider_user_id


def audience_settings(project_config: dict[str, Any] | None) -> AudienceSettings | None:
    """The configured audience proof, or ``None`` when the semantics are not one of :data:`SEMANTICS`."""
    raw = dict(dict((project_config or {}).get(SETTINGS_KEY) or {}).get(AUDIENCE_KEY) or {})
    semantics = str(raw.get("semantics") or "").strip()
    if semantics not in SEMANTICS:
        return None
    ttl = raw.get("receipt_ttl_hours", DEFAULT_TTL_HOURS)
    ttl = ttl if type(ttl) is int and 1 <= ttl <= MAX_TTL_HOURS else DEFAULT_TTL_HOURS
    return AudienceSettings(semantics=semantics, principal_user_id=str(raw.get("principal_user_id") or "").strip(),
                            outsider_user_id=str(raw.get("outsider_user_id") or "").strip(), ttl_hours=ttl)


async def _configured(db: AsyncSession, run: WorkflowRun, role: str) -> tuple[AudienceSettings, str]:
    await db.get(Project, run.project_id, populate_existing=True)
    settings = audience_settings(await get_project_config(run.project_id, db))
    principal = settings.principal_for(role) if settings is not None else ""
    if settings is None or not principal:
        raise AudienceProofError(CODE_NEEDS_CONFIGURATION, f"no {role} principal is configured for the audience "
                                 f"proof (project setting {AUDIENCE_CONFIG_PATH})",
                                 failure_class=CLASS_NEEDS_CONFIGURATION)
    if role == ROLE_OUTSIDER and principal == settings.principal_user_id:
        raise AudienceProofError(CODE_NEEDS_CONFIGURATION, "the outsider must not be the audience principal",
                                 failure_class=CLASS_NEEDS_CONFIGURATION)
    return settings, principal


async def audience_configuration_refusal(db: AsyncSession, run: WorkflowRun) -> str:
    """For the pre-publication preflight: ``""`` when P and O are configured as usable accounts, else why
    not (``needs_configuration`` before card (b); the ACL facts are checked at issue, once the page exists)."""
    try:
        settings, principal = await _configured(db, run, ROLE_AUDIENCE)
        _settings, outsider = await _configured(db, run, ROLE_OUTSIDER)
    except AudienceProofError as error:
        return error.detail
    for role, user_id in ((ROLE_AUDIENCE, principal), (ROLE_OUTSIDER, outsider)):
        user = await db.get(User, user_id)
        if user is None or not user.is_active or user.account_type != "human":
            return f"the configured {role} principal is not an active human account"
        if user.id == run.requested_by:
            return f"the configured {role} principal is the run's requester"
        if await _user_is_admin(db, user.id):
            return f"the configured {role} principal is an admin: admin access is never audience proof"
        workspace_role = await get_project_role_for_user(db, user.id, run.project_id)
        if workspace_role in AUTHOR_ROLES:
            return f"the configured {role} principal holds the Workspace role {workspace_role}"
        if role == ROLE_AUDIENCE and workspace_role is None:
            return "the configured audience principal cannot read the Workspace"
        if role == ROLE_OUTSIDER and (workspace_role is None) != (settings.semantics == SEMANTICS_WORKSPACE):
            return f"the configured outsider does not fit the audience semantics {settings.semantics}"
    return ""


async def principal_checks(db: AsyncSession, *, role: str, user_id: str, settings: AudienceSettings,
                           publication: ConfirmedPublication, requester_id: str | None, refusal_class: str
                           ) -> dict[str, Any]:
    """The account/role/ACL snapshot of the configured principal, or :class:`AudienceProofError`."""
    from ...knowledge.access.acl_keys import reader_principal_keys
    from ...knowledge.access.source_acl import acl_enforcement_enabled, load_source_acl

    def refuse(detail: str) -> AudienceProofError:
        return AudienceProofError(CODE_PRINCIPAL, f"the {role} principal {detail}", failure_class=refusal_class)

    user = await db.get(User, user_id, populate_existing=True) if user_id else None
    if user is None:
        raise refuse("does not exist")
    if not user.is_active or user.account_type != "human":
        raise refuse("is not an active human account")
    if requester_id and user.id == requester_id:
        raise refuse("is the run's requester")
    if role == ROLE_OUTSIDER and user.id == settings.principal_user_id:
        raise refuse("is the audience principal")
    if await _user_is_admin(db, user.id):
        raise refuse("is an admin: admin access is never audience proof")
    workspace_role = await get_project_role_for_user(db, user.id, publication.workspace_id)
    if workspace_role in AUTHOR_ROLES:
        raise refuse(f"holds the Workspace role {workspace_role}: an author/admin is not the audience")
    acl = await load_source_acl(db, publication.workspace_id, publication.source_key)
    keys = reader_principal_keys(user)
    admitted = acl is not None and bool(set(keys) & set(acl.principal_keys))
    if settings.semantics == SEMANTICS_SOURCE and not await acl_enforcement_enabled(db, publication.workspace_id):
        raise AudienceProofError(CODE_NEEDS_CONFIGURATION, "source-restricted audience semantics need the Workspace "
                                 "setting knowledge_source_acl.enforce (a configuration dependency)",
                                 failure_class=CLASS_NEEDS_CONFIGURATION)
    if role == ROLE_AUDIENCE:
        if workspace_role is None:
            raise refuse("cannot read the Workspace")
        if settings.semantics == SEMANTICS_WORKSPACE and acl is not None:
            raise AudienceProofError(CODE_NEEDS_CONFIGURATION, "workspace-reader semantics, but the page's source is "
                                     "restricted", failure_class=CLASS_NEEDS_CONFIGURATION)
        if settings.semantics == SEMANTICS_SOURCE and (acl is None or not admitted):
            raise refuse("is not admitted by the restricted source")
    elif settings.semantics == SEMANTICS_WORKSPACE:
        if workspace_role is not None:
            raise refuse("can read the Workspace: the workspace-reader outsider must not")
    else:
        if workspace_role is None:
            raise refuse("cannot read the Workspace: the source-restricted outsider must be a reader")
        if acl is None or admitted:
            raise refuse("is not excluded by a restricted source")
    return {"principal_role": role, "principal_id": user.id, "semantics": settings.semantics,
            "workspace_role": workspace_role, "account_type": user.account_type, "active": True, "admin": False,
            "restricted": acl is not None, "principal_admitted": admitted}
