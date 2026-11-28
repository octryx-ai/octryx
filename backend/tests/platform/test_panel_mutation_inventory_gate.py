"""Structural gate: every served cookie-authenticated panel mutation is behind the CSRF boundary and opens
with an approved active-principal guard; the inventory comes from ``app.routes``, the routes actually served."""

from __future__ import annotations

import inspect
import textwrap
from dataclasses import dataclass
from pathlib import Path

from app.main import app
from app.panel_csrf_policy import PANEL_PATH_MARKER, is_guarded_panel_path
from app.web._helpers import api_guards
from tests.support.panel_mutation_inventory_support import APPROVED_PRINCIPAL_GUARDS, guard_placement

ROUTERS_DIR = Path(api_guards.__file__).resolve().parents[1] / "routers"


SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS", "TRACE"})


#: Router modules that declare cookie-authenticated panel mutations, as
#: inventoried for the cookie mutation guard. ``chat_approvals`` is the one non-``panel_*`` module in
#: the set; its panel routes, and those of ``panel_identity_exec_policies`` which it includes, are the
#: only ones also served at the root.
PANEL_MUTATION_MODULES = frozenset(
    {
        "chat_approvals.py",
        "panel_agent_designer.py",
        "panel_agents.py",
        "panel_analytics.py",
        "panel_branding_voice.py",
        "panel_channels.py",
        "panel_connector_lifecycle.py",
        "panel_connectors.py",
        "panel_corp_identities.py",
        # Spec Studio: a Workspace's Corporate Identity and a profile's Studio locks.
        "panel_corp_identity_workspace.py",
        "panel_egress.py",
        "panel_engineering_knowledge.py",
        "panel_engineering_knowledge_federation.py",
        "panel_engineering_knowledge_review.py",
        "panel_entity_graph.py",
        "panel_identity_exec_policies.py",
        "panel_inbound_webhooks.py",
        "panel_mcp_capabilities.py",
        "panel_mcp_servers.py",
        "panel_model_routes.py",
        "panel_named_connections.py",
        "panel_office.py",
        "panel_office_fallback.py",
        "panel_policy_lists.py",
        "panel_project_design_sync.py",
        "panel_project_design_trace.py",
        "panel_projects_a.py",
        "panel_projects_b.py",
        "panel_projects_c.py",
        "panel_provider_runtime.py",
        "panel_providers.py",
        "panel_research_policies.py",
        "panel_rest_connectors.py",
        "panel_runtime_settings.py",
        "panel_runtimes.py",
        "panel_secrets_flags.py",
        "panel_task_management.py",
        "panel_tasks.py",
        "panel_users.py",
        "panel_webhooks.py",
        "panel_workspace_composition.py",
    }
)


#: State-changing routes declared in an inventoried module that are **not** on the
#: panel surface, and therefore outside this boundary. They are the approvals and
#: budget actions ``chat_approvals`` also serves under ``/chat/api/...``
#: and ``/admin/...``; like the rest of that surface they still rely on the
#: ``SameSite`` cookie attribute alone. Recorded here so the set stays classified
#: and visible — extending the boundary to them is the documented follow-up, and
#: anything newly added here has to be an explicit decision, not a drift.
KNOWN_UNGUARDED_MUTATIONS_IN_PANEL_MODULES = frozenset(
    {
        ("POST", "/admin/budget-policies"),
        # "Always for this Workspace" is the third answer to the same session approval.
        ("POST", "/admin/chat/api/approvals/{approval_id}/always"),
        ("POST", "/admin/chat/api/approvals/{approval_id}/approve"),
        ("POST", "/admin/chat/api/approvals/{approval_id}/reject"),
        ("POST", "/budget-policies"),
        ("POST", "/chat/api/approvals/{approval_id}/always"),
        ("POST", "/chat/api/approvals/{approval_id}/approve"),
        ("POST", "/chat/api/approvals/{approval_id}/reject"),
    }
)


@dataclass(frozen=True)
class ServedMutation:
    method: str
    path: str
    handler: str
    module: str
    source: str

    def __str__(self) -> str:
        return f"{self.module}::{self.handler} ({self.method} {self.path})"


def _served_mutations() -> list[ServedMutation]:
    served: list[ServedMutation] = []
    for route in app.routes:
        endpoint = getattr(route, "endpoint", None)
        methods = set(getattr(route, "methods", None) or []) - SAFE_METHODS
        if endpoint is None or not methods:
            continue
        try:
            source_file = inspect.getsourcefile(endpoint)
            source = textwrap.dedent(inspect.getsource(endpoint))
        except (OSError, TypeError):  # pragma: no cover - not reachable today
            source_file, source = None, ""
        module = Path(source_file).name if source_file else "<unknown>"
        for method in sorted(methods):
            served.append(
                ServedMutation(
                    method=method,
                    path=route.path,
                    handler=getattr(endpoint, "__name__", "<unnamed>"),
                    module=module,
                    source=source,
                )
            )
    return served


SERVED_MUTATIONS = _served_mutations()


def _is_panel_surface_path(path: str) -> bool:
    return "panel" in path.strip("/").split("/")


PANEL_SURFACE_MUTATIONS = [m for m in SERVED_MUTATIONS if _is_panel_surface_path(m.path)]


GUARDED_MUTATIONS = [m for m in SERVED_MUTATIONS if is_guarded_panel_path(m.path)]


def test_the_served_inventory_is_not_empty():
    # A scan that silently matched nothing would make every gate below pass.
    assert len(GUARDED_MUTATIONS) > 200, (
        f"panel mutation scan collapsed to {len(GUARDED_MUTATIONS)} served route entries"
    )
    assert len(SERVED_MUTATIONS) > len(GUARDED_MUTATIONS), "the scan found nothing outside the panel"
    # Both mounts of the twice-included approvals router must be in the inventory,
    # or the gate would be blind to whichever one it missed.
    root_mounted = {(m.method, m.path) for m in GUARDED_MUTATIONS if m.path.startswith("/chat/api/panel/")}
    assert root_mounted, "the root-mounted panel routes are missing from the inventory"
    assert root_mounted <= {
        (m.method, m.path.removeprefix("/admin"))
        for m in GUARDED_MUTATIONS
        if m.path.startswith("/admin/chat/api/panel/")
    }, "a panel route is served at the root without its /admin twin being inventoried"


def test_every_served_panel_mutation_is_on_the_csrf_guarded_surface():
    outside = sorted({(m.method, m.path) for m in PANEL_SURFACE_MUTATIONS if not is_guarded_panel_path(m.path)})
    assert outside == [], (
        f"state-changing panel routes the CSRF boundary does not recognise: {outside}. "
        f"The boundary matches {PANEL_PATH_MARKER!r}."
    )
    assert {(m.method, m.path) for m in PANEL_SURFACE_MUTATIONS} == {
        (m.method, m.path) for m in GUARDED_MUTATIONS
    }


def test_every_served_panel_mutation_comes_from_an_inventoried_module():
    undeclared = sorted({f"{m.module}::{m.handler}" for m in GUARDED_MUTATIONS if m.module not in PANEL_MUTATION_MODULES})
    assert undeclared == [], f"panel mutations from undeclared modules: {undeclared}"
    missing = PANEL_MUTATION_MODULES - {m.module for m in GUARDED_MUTATIONS}
    assert missing == set(), (
        f"declared panel mutation modules that serve nothing: {sorted(missing)}. "
        "A module whose routes are no longer mounted must be removed from the declaration, "
        "not left in it — otherwise its routes could go unserved unnoticed."
    )
    for mutation in GUARDED_MUTATIONS:
        assert (ROUTERS_DIR / mutation.module).is_file(), f"{mutation} is not declared under {ROUTERS_DIR}"


def test_no_state_changing_route_in_an_inventoried_module_is_unclassified():
    unclassified = sorted(
        {
            (m.method, m.path)
            for m in SERVED_MUTATIONS
            if m.module in PANEL_MUTATION_MODULES
            and not is_guarded_panel_path(m.path)
            and (m.method, m.path) not in KNOWN_UNGUARDED_MUTATIONS_IN_PANEL_MODULES
        }
    )
    assert unclassified == [], f"unclassified state-changing routes in panel modules: {unclassified}"
    stale = sorted(
        KNOWN_UNGUARDED_MUTATIONS_IN_PANEL_MODULES
        - {(m.method, m.path) for m in SERVED_MUTATIONS if m.module in PANEL_MUTATION_MODULES}
    )
    assert stale == [], f"recorded unguarded routes that no longer exist: {stale}"


def test_the_principal_guard_opens_every_served_panel_mutation_handler():
    problems = [f"{mutation}: {guard_placement(mutation.source).problem}" for mutation in GUARDED_MUTATIONS if not guard_placement(mutation.source).ok]
    assert problems == [], (
        "panel mutation handlers whose active-principal guard is not the first "
        f"executable statement: {sorted(set(problems))}. Open the handler with "
        f"`await <guard>(request, db)` using one of {sorted(APPROVED_PRINCIPAL_GUARDS)}."
    )
    used = {guard_placement(m.source).guard for m in GUARDED_MUTATIONS}
    assert used <= APPROVED_PRINCIPAL_GUARDS and used, f"unexpected guard set: {sorted(used)}"
