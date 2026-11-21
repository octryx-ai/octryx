"""Reading a Custom REST list operation for an intake: the executor's own path, inside a data scope.

Every page goes through ``rest_connector.executor.run_operation``, the path a ``rest__`` tool call takes: the pinned
``custom_rest`` egress, the connection's auth (CSRF option included), the operation's pagination, the grant's scope
parameters injected last, the result filter on the parsed records, and one audit row per call. Nothing here sends a
request of its own.

**Data scope.** The API is reached with a technical account that may see more than anyone should sync. So an intake
names an Octryx **role** and the sync runs as exactly that role (``IntakeCallContext.acting_role``): its grant's scope
parameters and result filter apply, never the roles of whoever triggered the sync (they could be wider). An intake
without a role is refused when the list operation has any scoped grant (``custom_rest_role_required``): the
technical user never syncs unscoped data when the admin scoped the operation. Records the result filter drops are
counted (``dropped_out_of_scope``) in the run summary.

**Pages.** Page after page (the signed ``next_cursor``) until the operation says there is none, at most
``max_pages`` pages and ``max_items`` records per run. Only a read that reached the last page is ``complete``; a cut
read closes nothing for leaving it.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ....models import RestApiDefinition, RestApiOperation
from ...rest_connector.authorization import grants_of, matching_grants
from ...rest_connector.common import is_read_operation, tool_name_for
from ...rest_connector.connections import connection_for_call
from ...rest_connector.executor import run_operation
from ...rest_connector.response import locate_records
from ...rest_connector.runs import REFUSAL_CATEGORIES
from ...rest_connector.schema import cursor_param_name, declared_parameters
from ..servicenow.source import IntakeSourceError

CODE_DEFINITION_UNAVAILABLE = "custom_rest_definition_unavailable"
CODE_OPERATION_UNAVAILABLE = "custom_rest_operation_unavailable"
CODE_NOT_A_READ = "custom_rest_operation_not_a_read"
CODE_NO_CONNECTION = "custom_rest_no_connection"
CODE_ROLE_REQUIRED = "custom_rest_role_required"
CODE_ROLE_NOT_GRANTED = "custom_rest_role_not_granted"
CONFIG_CODES = frozenset({CODE_DEFINITION_UNAVAILABLE, CODE_OPERATION_UNAVAILABLE, CODE_NOT_A_READ, CODE_NO_CONNECTION,
                          CODE_ROLE_REQUIRED, CODE_ROLE_NOT_GRANTED})


@dataclass
class IntakeCallContext:
    """The server-owned context of an intake's REST call: the Workspace, the person or owner it runs for (audit), and
    the one role it acts as (``authorization.caller_roles`` then ignores every other role)."""

    user_id: str | None
    project_id: str
    db: AsyncSession
    acting_role: str | None = None
    roles: list[str] = field(default_factory=list)
    session_id: str | None = None

    @property
    def project_ids(self) -> list[str]:
        return [self.project_id]

    @property
    def project_config(self) -> dict[str, Any]:
        return {"project_id": self.project_id}


@dataclass(frozen=True)
class Page:
    records: list[Mapping[str, Any]]
    complete: bool
    dropped: int
    pages: int


def refusal(code: str, message: str) -> IntakeSourceError:
    """A configuration refusal: 409 at the API (``servicenow.source.source_error``), never the upstream's status."""
    error = IntakeSourceError(code, message)
    error.refusal = True
    return error


async def definition_by_key(db: AsyncSession, key: str) -> RestApiDefinition | None:
    return (await db.execute(select(RestApiDefinition).where(
        RestApiDefinition.key == key, RestApiDefinition.is_active.is_(True)))).scalars().first()


async def operation_of(db: AsyncSession, definition: RestApiDefinition, name: str) -> RestApiOperation | None:
    """The enabled operation by ``op_key``, its model-facing name or its full tool name."""
    rows = (await db.execute(select(RestApiOperation).where(RestApiOperation.definition_id == definition.id,
                                                            RestApiOperation.enabled.is_(True)))).scalars().all()
    for operation in rows:
        names = {operation.op_key, operation.llm_name or operation.op_key,
                 tool_name_for(definition.key, operation.llm_name or operation.op_key)}
        if name in names:
            return operation
    return None


async def resolve_list(db: AsyncSession, project_id: str, definition_key: str, operation_name: str,
                       ) -> tuple[RestApiDefinition, RestApiOperation]:
    """The intake's definition and read operation with a connection for the Workspace; refuses otherwise."""
    definition = await definition_by_key(db, definition_key)
    if definition is None:
        raise refusal(CODE_DEFINITION_UNAVAILABLE, "The intake's REST API is not active (Connections › REST APIs).")
    operation = await operation_of(db, definition, operation_name)
    if operation is None:
        raise refusal(CODE_OPERATION_UNAVAILABLE, "The intake's list operation is not enabled on this API.")
    if not is_read_operation(operation.method, bool(operation.read_only)):
        raise refusal(CODE_NOT_A_READ, "An intake lists records with a read operation, never a write.")
    if await connection_for_call(db, definition.id, project_id) is None:
        raise refusal(CODE_NO_CONNECTION, "This API has no active connection for the Workspace or the platform.")
    return definition, operation


def acting_role(operation: RestApiOperation, role: str | None, project_id: str) -> str:
    """The role the sync acts as; refuses an unscoped sync of a scoped operation and a role without a grant.

    Without a named role the operation may have only unscoped grants for this Workspace, and the sync acts as one of
    them (it then sees what any granted caller sees, nothing narrower exists)."""
    grants = [grant for grant in grants_of(operation) if grant.workspace_id in (None, project_id)]
    if role is None:
        if any(grant.scoped for grant in grants):
            raise refusal(CODE_ROLE_REQUIRED, "The list operation has scoped grants: name the role whose data scope "
                                              "the sync runs in.")
        if not grants:
            raise refusal(CODE_ROLE_NOT_GRANTED, "The list operation is granted to no role of this Workspace.")
        return grants[0].role
    if not matching_grants(operation, frozenset({role.lower()}), project_id):
        raise refusal(CODE_ROLE_NOT_GRANTED, "The intake's role holds no grant of the list operation here.")
    return role


def _failed(result: Mapping[str, Any]) -> IntakeSourceError:
    category = str(result.get("code") or "request_failed")
    error = IntakeSourceError(f"custom_rest_{category}", str(result.get("error") or "The REST call failed"),
                              http_status=(result.get("run") or {}).get("http_status"))
    error.refusal = category in REFUSAL_CATEGORIES
    return error


def _records(data: Any, records_path: str | None) -> list[Mapping[str, Any]]:
    found, _path = locate_records(data, records_path)
    if found is None:
        return [data] if isinstance(data, Mapping) else []
    return [record for record in found if isinstance(record, Mapping)]


@dataclass(frozen=True)
class OnePage:
    """One answered call: its records (after the result filter), how many the filter dropped, the next cursor."""

    records: list[Mapping[str, Any]]
    dropped: int
    next_cursor: str | None


async def call_read(db: AsyncSession, *, definition: RestApiDefinition, operation: RestApiOperation,
                    context: IntakeCallContext, arguments: Mapping[str, Any]) -> Mapping[str, Any]:
    """One audited executor call of a read as ``context``; raises ``IntakeSourceError`` on a refused or failed call.

    Shared by the Work intake and the Knowledge source: neither sends a request of its own."""
    tool_name = tool_name_for(definition.key, operation.llm_name or operation.op_key)
    result = await run_operation(db, definition=definition, operation=operation, tool_name=tool_name,
                                 params=dict(arguments), context=context)
    if "error" in result:
        raise _failed(result)
    return result


async def read_page(db: AsyncSession, *, definition: RestApiDefinition, operation: RestApiOperation,
                    context: IntakeCallContext, arguments: Mapping[str, Any], cursor: str | None) -> OnePage:
    """One page of the list operation at ``cursor`` (``None``: the first page)."""
    cursor_param = cursor_param_name(declared_parameters(operation))
    params = {**arguments, **({cursor_param: cursor} if cursor else {})}
    result = await call_read(db, definition=definition, operation=operation, context=context, arguments=params)
    return OnePage(records=_records(result.get("data"), operation.records_path),
                   dropped=int(result.get("dropped_out_of_scope") or 0), next_cursor=result.get("next_cursor") or None)


async def read_pages(db: AsyncSession, *, definition: RestApiDefinition, operation: RestApiOperation,
                     context: IntakeCallContext, arguments: Mapping[str, Any], max_items: int, max_pages: int,
                     ) -> Page:
    """Page through the list operation as ``context``; raises ``IntakeSourceError`` on a refused or failed call."""
    records: list[Mapping[str, Any]] = []
    dropped = pages = 0
    cursor: str | None = None
    complete = False
    while pages < max_pages and len(records) <= max_items:
        page = await read_page(db, definition=definition, operation=operation, context=context,
                               arguments=arguments, cursor=cursor)
        records.extend(page.records)
        dropped += page.dropped
        pages += 1
        cursor = page.next_cursor
        if not cursor:
            complete = True
            break
    if len(records) > max_items:
        records, complete = records[:max_items], False
    return Page(records=records, complete=complete, dropped=dropped, pages=pages)


__all__ = [
    "CODE_ROLE_NOT_GRANTED",
    "CODE_ROLE_REQUIRED",
    "CONFIG_CODES",
    "IntakeCallContext",
    "OnePage",
    "Page",
    "acting_role",
    "call_read",
    "definition_by_key",
    "operation_of",
    "read_page",
    "read_pages",
    "refusal",
    "resolve_list",
]
