"""Structural gate: no provider dispatch outside the registered owners.

The admission boundary only works if every dispatch owner goes through it, which
is a *structural* property — so it is checked structurally. ``dispatch_site_scan``
parses every module under ``app/`` and reports where a provider client is
constructed, where a ``.chat`` dispatch happens, and where the governed gateway
driver is named; this module compares that with the pinned inventory in
``app/services/model_gateway/dispatch_owners.py``.

Two things make this more than a plain text search:

- construction counts, not just dispatch. A module that builds a client and hands
  it to a helper is the owner, whichever file finally awaits ``chat``;
- the detector itself is under test. ``test_the_detector_catches_…`` mutates real
  evasion shapes (multi-line call, wrapper function, aliased client, ``driver=``
  from a constant, a bare ``.chat`` reference) and requires each to be reported,
  and ``test_the_detector_does_not_flag_…`` requires the look-alikes that are not
  dispatch sites (a ``chat`` method definition, a comment, a docstring, an
  unrelated ``_get_provider`` database helper) to stay unreported.

A gate whose detector is not itself tested can only be trusted as far as the
shapes someone thought of; these mutation controls are what that claim rests on.
"""

from __future__ import annotations

import pytest

from app.services.model_gateway.dispatch_owner_record import (
    DISPATCH_MODE_ADMITTED,
    DISPATCH_MODE_AUTHORITY,
    DISPATCH_MODE_CATALOG_ONLY,
    DISPATCH_MODES,
)
from app.services.model_gateway.dispatch_owners import (
    DISPATCH_OWNER_MODULES,
    DISPATCH_OWNERS,
    owners_for_mode,
)

from .dispatch_site_scan import (
    APP_ROOT,
    KIND_CHAT_DISPATCH,
    KIND_CLIENT_CONSTRUCTION,
    KIND_FACTORY_HANDOFF,
    KIND_GATEWAY_CONSTRUCTION,
    modules_with_kinds,
    scan_source,
)

# Modules that legitimately hold the machinery rather than consume it.
_BOUNDARY_PREFIXES = (
    "app/services/model_gateway/",
    "app/agent/providers/",
    "app/agent/core/runtime/runtime_admission_contract.py",
)

# Every way an owner may reach the admission authority. All of them live inside
# ``app/services/model_gateway`` — that package *is* the boundary.
_ADMISSION_ENTRY_POINTS = (
    "admit_runtimes_for_dispatch",
    "admit_client_kwargs_for_dispatch",
    "resolve_workspace_admission",
    "apply_model_policy_to_runtimes",
    "admit_gateway_runtimes",
    # A dispatch site whose Workspace is resolved by its caller still has to
    # verify the admission it was handed; that check is a boundary entry point too.
    "resolved_project_admission",
)


def _formatted(sites: dict) -> str:
    return "\n".join(f"  {module}:{site.line} [{site.kind}] {site.detail}" for module, site in sorted(sites.items()))


def test_every_module_that_builds_or_dispatches_a_client_is_a_registered_owner():
    found = modules_with_kinds(
        KIND_CLIENT_CONSTRUCTION, KIND_CHAT_DISPATCH, exclude_prefixes=_BOUNDARY_PREFIXES
    )
    unregistered = {module: site for module, site in found.items() if module not in DISPATCH_OWNER_MODULES}
    assert not unregistered, (
        "These modules construct a provider client or dispatch a completion without being "
        "registered in app/services/model_gateway/dispatch_owners.py:\n" + _formatted(unregistered)
    )


def test_no_module_outside_the_provider_factory_constructs_the_gateway_driver():
    constructing = modules_with_kinds(KIND_GATEWAY_CONSTRUCTION, exclude_prefixes=_BOUNDARY_PREFIXES)
    assert not constructing, (
        "The governed gateway driver may only be constructed by the provider factory:\n"
        + _formatted(constructing)
    )


def test_a_module_that_only_forwards_the_factory_never_dispatches_itself():
    """Transport into an owner is allowed; transport that also dispatches is not."""

    handoff = modules_with_kinds(KIND_FACTORY_HANDOFF, exclude_prefixes=_BOUNDARY_PREFIXES)
    dispatching = modules_with_kinds(
        KIND_CLIENT_CONSTRUCTION, KIND_CHAT_DISPATCH, exclude_prefixes=_BOUNDARY_PREFIXES
    )
    offenders = {
        module: site
        for module, site in dispatching.items()
        if module in handoff and module not in DISPATCH_OWNER_MODULES
    }
    assert not offenders, "A factory-forwarding module that dispatches is an owner:\n" + _formatted(offenders)


def test_every_admitted_owner_reaches_the_admission_boundary():
    offenders: list[str] = []
    for owner in owners_for_mode(DISPATCH_MODE_ADMITTED):
        source = (APP_ROOT.parent / owner.admission_module).read_text(encoding="utf-8")
        if not any(entry in source for entry in _ADMISSION_ENTRY_POINTS):
            offenders.append(f"  {owner.key} ({owner.admission_module})")
    assert not offenders, (
        "These registered owners dispatch without reaching the admission boundary:\n" + "\n".join(offenders)
    )


def test_catalog_only_owners_never_dispatch_a_completion():
    offenders: list[str] = []
    for owner in owners_for_mode(DISPATCH_MODE_CATALOG_ONLY):
        for module in owner.modules:
            source = (APP_ROOT.parent / module).read_text(encoding="utf-8")
            for site in scan_source(source, module=module):
                if site.kind == KIND_CHAT_DISPATCH:
                    offenders.append(f"  {owner.key} ({module}:{site.line}): {site.detail}")
    assert not offenders, (
        "A catalog_only owner holds the deny-everything admission and must not chat:\n" + "\n".join(offenders)
    )


def test_inventory_entries_are_well_formed():
    assert DISPATCH_OWNERS, "the inventory must not be empty"
    for key, owner in DISPATCH_OWNERS.items():
        assert owner.key == key
        assert owner.mode in DISPATCH_MODES, f"{key} has an unknown mode {owner.mode!r}"
        assert owner.category.strip(), f"{key} has no category"
        for module in owner.modules:
            assert (APP_ROOT.parent / module).is_file(), f"{key} points at a missing module {module}"
    # Exactly one module is allowed to consume the contract without resolving it.
    assert len(owners_for_mode(DISPATCH_MODE_AUTHORITY)) == 1


def test_every_issue_category_has_a_registered_owner():
    """The categories the owner inventory names, each mapped to at least one real owner."""

    categories = {owner.category for owner in DISPATCH_OWNERS.values()}
    for expected in (
        "main chat turn",
        "chat pre-turn task extraction",
        "knowledge graph extraction/summarization/keywords",
        "secure-work worker",
        "sub-agent/call-agent",
        "summarizer",
        "risk analysis",
        "admin test surface",
    ):
        assert expected in categories, f"no registered dispatch owner for category {expected!r}"


# --- mutation controls: the detector under test ------------------------------

_EVASIONS = {
    # The receiver on its own line: a per-line regular expression sees only
    # ``.chat(`` with nothing in front of it and lets this through.
    "receiver_on_a_previous_line": (
        "async def run(client):\n"
        "    return await (\n"
        "        client\n"
        "        .chat(messages=[], model='m')\n"
        "    )\n"
    ),
    "wrapper_function_dispatch": (
        "async def _dispatch(client, **kwargs):\n"
        "    return await client.chat(**kwargs)\n"
    ),
    "client_stored_on_self": (
        "class Runner:\n"
        "    async def go(self):\n"
        "        return await self._client.chat(messages=[])\n"
    ),
    "chat_reference_handed_elsewhere": (
        "def wire(client, register):\n"
        "    register(client.chat)\n"
    ),
    "subscripted_receiver": (
        "async def run(clients):\n"
        "    return await clients[0].chat(messages=[])\n"
    ),
}

_GATEWAY_EVASIONS = {
    "driver_string_literal": (
        "from app.agent.providers import get_provider\n"
        "client = get_provider(provider_name='litellm', driver='litellm_gateway')\n"
    ),
    "driver_from_constant": (
        "from app.agent.providers import get_provider\n"
        "from app.services.model_gateway.litellm.runtime_admission import LITELLM_GATEWAY_DRIVER\n"
        "client = get_provider(provider_name='litellm', driver=LITELLM_GATEWAY_DRIVER)\n"
    ),
    "driver_from_qualified_constant": (
        "from app.agent.providers import get_provider\n"
        "from app.services.model_gateway.litellm import runtime_admission\n"
        "client = get_provider(driver=runtime_admission.LITELLM_GATEWAY_DRIVER)\n"
    ),
    "direct_driver_class": (
        "from app.agent.providers.litellm_gateway import LiteLLMGatewayClient\n"
        "client = LiteLLMGatewayClient(endpoint_url='https://x/v1')\n"
    ),
}

_LOOK_ALIKES = {
    "chat_method_definition": (
        "class Client:\n"
        "    async def chat(self, messages, model):\n"
        "        return {}\n"
    ),
    "commented_out_dispatch": "# result = await client.chat(messages=[])\n",
    "docstring_mentioning_dispatch": '"""Calls client.chat(...) somewhere else."""\n',
    "unrelated_get_provider_helper": (
        "async def _get_provider(db, provider_id):\n"
        "    return await db.get(ProviderConfigRow, provider_id)\n"
        "\n"
        "async def use(db):\n"
        "    return await _get_provider(db, 'x')\n"
    ),
    "module_named_chat_imported": (
        "from app.services.live_validation.chat import _latest_assistant_message\n"
        "value = _latest_assistant_message\n"
    ),
}


@pytest.mark.parametrize("name", sorted(_EVASIONS))
def test_the_detector_catches_indirect_dispatch_shapes(name: str):
    sites = scan_source(_EVASIONS[name], module="app/probe.py")
    assert any(site.kind == KIND_CHAT_DISPATCH for site in sites), (
        f"the {name} shape would evade the structural gate"
    )


_CONSTRUCTION_EVASIONS = {
    # Nothing here dispatches: the client is handed to another module, which is
    # exactly the indirection a ``.chat`` search cannot see.
    "construction_handed_to_another_module": (
        "from app.agent.providers import get_provider\n"
        "def wire(register):\n"
        "    register(get_provider(provider_name='openrouter'))\n"
    ),
    "construction_under_an_alias": (
        "from app.agent.providers import get_provider as _build\n"
        "def wire():\n"
        "    return _build(provider_name='openrouter')\n"
    ),
    "construction_from_an_injected_factory": (
        "async def run(provider_factory, **kwargs):\n"
        "    return provider_factory(provider_name='openrouter', **kwargs)\n"
    ),
}


@pytest.mark.parametrize("name", sorted(_CONSTRUCTION_EVASIONS))
def test_the_detector_catches_client_construction_without_dispatch(name: str):
    sites = scan_source(_CONSTRUCTION_EVASIONS[name], module="app/probe.py")
    assert any(site.kind == KIND_CLIENT_CONSTRUCTION for site in sites), (
        f"the {name} shape would evade the structural gate"
    )


@pytest.mark.parametrize("name", sorted(_GATEWAY_EVASIONS))
def test_the_detector_catches_gateway_construction_shapes(name: str):
    sites = scan_source(_GATEWAY_EVASIONS[name], module="app/probe.py")
    kinds = {site.kind for site in sites}
    assert KIND_GATEWAY_CONSTRUCTION in kinds, f"the {name} shape would evade the gateway gate"


@pytest.mark.parametrize("name", sorted(_LOOK_ALIKES))
def test_the_detector_does_not_flag_look_alikes(name: str):
    sites = scan_source(_LOOK_ALIKES[name], module="app/probe.py")
    assert not [site for site in sites if site.kind != KIND_FACTORY_HANDOFF], (
        f"the {name} shape is not a dispatch site: {sites}"
    )
