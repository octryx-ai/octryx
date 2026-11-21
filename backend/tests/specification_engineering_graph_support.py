"""Test fixture: the engineering B that consumes an accepted spec, and the spec parent's typed offer into it.

``spec_engineering_definition`` is a NEW authored graph (key :data:`ENGINEERING_KEY`), derived from exactly the B
seed (:data:`BASE_DIGEST`) without changing that seed or any historic version: every Red/Green/lint/code-review/tree/CI/
merge/publication/receipt node, check and edge stays as it is. It adds only

- ``start.handoff_inputs: [spec]``: the spec arrives only through the accepted typed handoff, resolved for the actual
  caller (``specification.integration``); a direct start is refused before any ticket or branch write;
- the spec as an explicit input of Clarify and of both documentation phases, and on the test-contract card
  (``shows: spec``: the exact criteria, their recorded coverage and the confirmation they come from);
- ``decider: spec_origin`` on the post-merge functional acceptance (a), publication (b), late acceptance and
  exception decisions. Engineering, test- and documentation-contract confirmations stay with the engineer, who also
  keeps owner, execution, Session and runtime rights.

``specification_engineering_definition`` is the spec-from-idea parent with, before its terminal ``done``, one typed
``handoff/v1`` offer of its confirmed spec into an exact pinned version of that graph (version id + canonical
checksum). Its inputs are explicit: an existing Work item, repository, connections, the spec's source ids and a named
engineer. It is a connective controlled fixture, not Chain 1: no ticket creation, link or notification; no provider
write and no scope grant of its own (the receiver's rights are rechecked at acceptance).

Neither definition ships with the platform; a test publishes a version explicitly, as an admin would.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

# The one workflow definition this graph is derived from, a test fixture only: the platform does not ship it as a
# workflow. Its fragment box compiles with the shipped fragments (``seeding.compiled_seed``).
BASE_SEED_PATH = Path(__file__).resolve().parent / "fixtures" / "engineering_graph_base.json"
BASE_KEY = "feature-delivery-tdd"
# The B seed this graph is derived from; a changed seed needs an explicit, reviewed re-derivation.
# re-derived after the tests-first wording (new tests may fail at the import of new code).
BASE_DIGEST = "sha256:b0fc51cda308c0ac6ddb7224b300efa926cb862c6a4c9de1afb466ef18a502df"
ENGINEERING_KEY = "feature-delivery-from-spec"
ENGINEERING_NAME = "Feature delivery from an accepted specification (TDD)"
ENGINEERING_DESCRIPTION = (
    "The engineering B of an accepted specification handoff: the engineer's own Clarify, test contract and "
    "documentation contract on the exact accepted spec, failing tests first, green, an independent review, the "
    "reviewed tree pushed, CI and the merge watched; then the spec's confirmer decides the functional acceptance, "
    "the publication and any exception, and the platform publishes and proves the page."
)
SPEC_ORIGIN_NODES = ("accept_functional", "confirm_publication", "acceptance_open", "confirm_exception")
SPEC_INPUT_PHASES = ("clarify", "doc_draft", "doc_final")
OFFER_NODE = "engineering"
HANDOFF_TIMEOUT_SECONDS = 259200

_CLARIFY = (" Your inputs carry the accepted specification (spec): use its exact, case-sensitive criterion IDs and "
            "their Given/When/Then; never renumber them. Each accepted criterion needs a genuine new test or "
            "manual_only with its reason; the server checks this against the accepted handoff as you, and the "
            "specification's sources stay subject to your own current access.")
_DOCS = (" The accepted specification (spec) is an input: describe its user stories and criteria for its "
         "documentation audience; the platform's publication target and audience come from the confirmed "
         "contract, never from a guess.")


def base_seed() -> dict[str, Any]:
    """The base seed (``BASE_SEED_PATH``) with its compiled ``definition``."""
    from app.services.workflow_runs.seeding import compiled_seed

    return compiled_seed(json.loads(BASE_SEED_PATH.read_text(encoding="utf-8")))


def _base() -> dict[str, Any]:
    from app.services.workflow_runs.seeding import definition_digest

    seed = base_seed()
    if definition_digest(seed["definition"]) != BASE_DIGEST:
        raise RuntimeError("The S1 B seed changed; re-derive the accepted-spec engineering graph explicitly.")
    return copy.deepcopy(seed["definition"])


def spec_engineering_definition() -> dict[str, Any]:
    """A fresh copy of the new authored engineering graph (never a seed, never a historic version)."""
    definition = _base()
    nodes = {node["id"]: node for node in definition["nodes"]}
    nodes["start"]["config"] = {"handoff_inputs": ["spec"]}
    for node_id in SPEC_INPUT_PHASES:
        config = nodes[node_id]["config"]
        config["inputs"] = [*[kind for kind in config.get("inputs") or [] if kind != "spec"], "spec"]
        contract = config["workflow_contract"]
        contract["when_to_use"] = contract["when_to_use"].replace(
            "The requester decides the functional acceptance and the publication separately",
            "The person who confirmed the accepted specification decides the functional acceptance and the "
            "publication separately") + (_CLARIFY if node_id == "clarify" else _DOCS)
    nodes["contract"]["config"]["shows"] = "spec"
    for node_id in SPEC_ORIGIN_NODES:
        nodes[node_id]["config"]["decider"] = "spec_origin"
    return definition


def engineering_handoff(*, workspace_id: str, work_item_id: str, repository: str, connection_ids: list[str],
                        source_ids: list[str], engineer_id: str,
                        timeout_seconds: int = HANDOFF_TIMEOUT_SECONDS) -> dict[str, Any]:
    """The closed handoff/v1 contract of the offer; every scope value is explicit, nothing is inferred."""
    return {"schema_version": "handoff/v1", "owner": f"person:{engineer_id}", "artefacts": ["spec"],
            "acceptance": ("Engineer the exact confirmed specification in this Work item and repository: its "
                           "stable criteria become your test contract; you own the run, its Session and runtime."),
            "scope": {"workspace_id": workspace_id, "work_item_id": work_item_id, "repository": repository,
                      "service_ids": [], "connection_ids": list(connection_ids), "source_ids": list(source_ids)},
            "detach": False, "timeout_seconds": timeout_seconds, "deputy": None}


def specification_engineering_definition(*, child_version_id: str, child_checksum: str,
                                         **scope: Any) -> dict[str, Any]:
    """The spec-from-idea parent offering its confirmed spec into the pinned engineering B before ``done``."""
    from tests.specification_definition_support import specification_definition

    definition = specification_definition()
    definition["edges"] = [edge for edge in definition["edges"] if edge["id"] != "accepted"]
    done = next(node for node in definition["nodes"] if node["id"] == "done")
    done["label"] = "Specification accepted and engineered"
    definition["nodes"].insert(len(definition["nodes"]) - 1, {
        "id": OFFER_NODE, "type": "sub_workflow", "label": "Hand the accepted specification to engineering",
        "config": {"workflow_key": ENGINEERING_KEY, "child_version_id": child_version_id,
                   "child_checksum": child_checksum, "handoff": engineering_handoff(**scope)}})
    definition["nodes"].extend([
        {"id": "engineering-exception", "type": "outcome", "label": "Engineered with a decided exception",
         "config": {"outcome": "done_with_exception"}},
        {"id": "engineering-blocked", "type": "outcome", "label": "Engineering blocked, declined or timed out",
         "config": {"outcome": "blocked"}},
        {"id": "engineering-stopped", "type": "outcome", "label": "Engineering stopped",
         "config": {"outcome": "stopped"}}])
    definition["edges"].extend([
        {"id": "accepted", "source": "confirm-spec", "target": OFFER_NODE, "when": "confirmed"},
        {"id": "engineered", "source": OFFER_NODE, "target": "done", "when": "done"},
        {"id": "engineered-exception", "source": OFFER_NODE, "target": "engineering-exception",
         "when": "done_with_exception"},
        {"id": "engineering-blocked", "source": OFFER_NODE, "target": "engineering-blocked", "when": "blocked"},
        {"id": "engineering-stopped", "source": OFFER_NODE, "target": "engineering-stopped", "when": "stopped"}])
    return definition


__all__ = ["BASE_DIGEST", "BASE_KEY", "BASE_SEED_PATH", "ENGINEERING_DESCRIPTION", "ENGINEERING_KEY",
           "ENGINEERING_NAME", "OFFER_NODE", "SPEC_ORIGIN_NODES", "base_seed", "engineering_handoff",
           "spec_engineering_definition", "specification_engineering_definition"]
