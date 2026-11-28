"""The examination contract cannot be bypassed: every scanner use, consumer and result-consuming edge is listed
with the property case that asserts it, so a new one fails here until it has one."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.content_security.examination_edge_cases import EDGE_CASES
from tests.content_security.examination_guard_support import edge, sites
from tests.content_security.test_examination_contract import CASES

BACKEND = Path(__file__).resolve().parents[2]
ROOTS = (BACKEND / "app", BACKEND.parent / "clients" / "octryx-claude" / "octryx_claude")

CONSUMERS = frozenset({
    "app.services.content_detection.preview",
    "app.services.content_security.format_chat_messages",
    "app.services.content_security.format_request_body",
    "app.services.content_routing.chat",
    "app.services.content_routing.client_tool_results",
    "app.services.content_routing.decision",
    "app.services.content_routing.tool_results",
    "app.services.content_security.message_trust",
    "app.services.content_security.model_call",
    "app.services.content_security.enforcement_call",
    "app.services.content_security.model_call_fields",
    "app.services.content_security.transport",
    "app.services.content_detection.request_examination",
    "app.services.content_detection.final_check",
    "app.services.content_routing.gateway_outcome",
    "app.services.content_security.model_call_outbound",
    "app.services.content_security.model_call_outcome",
    "app.services.security_analyzer.content_command",
    "app.services.content_security.enforcement_inbound",
    "app.services.model_gateway.inbound.codex_seat",
    "app.services.model_gateway.inbound.openai_service",
    "app.services.model_gateway.inbound.seat",
    "app.tools.result_content",
    "app.services.model_gateway.inbound.service",
    "app.services.model_gateway.inbound.seat_content",
    "app.agent.providers.base",
    "app.api.routes.agent_gateway.agent_gateway",
    "octryx_claude.content_hooks",
    "octryx_claude.post_tool_use_hook",
})


_CONTRACT = "app.services.content_detection.examination"
_DECISION = "app.services.content_routing.decision"
_CLIENT_TOOLS = "app.services.content_routing.client_tool_results"
_GATEWAY = "app.services.content_routing.gateway"
_BODY = "app.services.content_security.format_request_body"
_SCAN = f"{_BODY}.GatewayScan"
_PLAN = "app.services.content_security.enforcement_inbound"
_TOOL_RESULTS = "app.services.content_routing.tool_results"
_MODEL_CALL = "app.services.content_security.model_call"
_CALL = "app.services.content_security.enforcement_call"
_FIELDS = "app.services.content_security.model_call_fields"
_REQUEST = "app.services.content_detection.request_examination"
_INBOUND = "app.services.model_gateway.inbound"
_SERVICE = f"{_INBOUND}.service"
_SEAT_CONTENT = f"{_INBOUND}.seat_content"
_OUTCOME = "app.services.content_routing.gateway_outcome"
_FINAL = "app.services.content_detection.final_check"
_OUTBOUND = "app.services.content_security.model_call_outbound"
_CALL_OUTCOME = "app.services.content_security.model_call_outcome"

#: Every result-consuming edge (module, enclosing definition, interface) → the case that asserts it: the consumer
#: module's own case, or an edge case (``examination_edge_cases``) where the module's case does not reach the edge.
EDGES: dict[str, str] = {
    edge("app.agent.providers.base", "_measured.measured", f"{_MODEL_CALL}.enforced_chat"): "app.agent.providers.base",
    edge("app.api.routes.agent_gateway.agent_gateway", "tool_executed", f"{_CLIENT_TOOLS}.launcher_tool_result"):
        "app.api.routes.agent_gateway.agent_gateway",
    edge("app.services.content_detection.preview", "preview", f"{_CONTRACT}.examine_text"):
        "app.services.content_detection.preview",
    edge("app.services.content_routing.chat", "chat_content_decision", f"{_DECISION}.scan_for"):
        "app.services.content_routing.chat",
    edge("app.services.content_routing.chat", "chat_content_decision", f"{_DECISION}.decide_model_content"):
        "app.services.content_routing.chat",
    edge(_CLIENT_TOOLS, "launcher_tool_result", f"{_TOOL_RESULTS}.check_tool_result"): "app.api.routes.agent_gateway.agent_gateway",
    edge(_DECISION, "enforcement_budget", f"{_CONTRACT}.RequestBudget"): _DECISION,
    edge(_DECISION, "scan_for", f"{_CONTRACT}.compose"): _DECISION,
    edge(_DECISION, "scan_for", f"{_CONTRACT}.examine"): _DECISION,
    edge(_BODY, "examine_request_body", f"{_CONTRACT}.compose"): _BODY,
    edge(_BODY, "_with_fields", f"{_CONTRACT}.compose"): _BODY,
    edge(_BODY, "examine_request_body", f"{_CONTRACT}.examine"): _BODY,
    edge(_PLAN, "enforce_inbound", f"{_BODY}.examine_request_body"): _PLAN,
    edge(_PLAN, "enforce_inbound", f"{_GATEWAY}.fixed_refusal"): _PLAN,
    edge(_PLAN, "enforce_inbound", f"{_GATEWAY}.handling_refusal"): "edge:gateway_plan_actions",
    edge(_PLAN, "enforce_inbound", f"{_CLIENT_TOOLS}.client_tool_result_denial"): "edge:gateway_tool_grouping",
    **{edge(_PLAN, "enforce_inbound", f"{_SCAN}.secret_kinds", site): "edge:gateway_plan_actions"
       for site in (1, 2, 3, 4, 5, 6)},
    edge(_PLAN, "enforce_inbound", f"{_GATEWAY}.fixed_refusal", 2): _PLAN,
    edge(_PLAN, "_masked", f"{_BODY}.examine_request_body"): _PLAN,
    edge(_BODY, "mask_gateway_body", f"{_REQUEST}.RequestExaminer"): _BODY,
    edge(_PLAN, "_decided", f"{_DECISION}.decide_model_content"): "edge:gateway_cedar_conversion",
    edge(_PLAN, "enforce_inbound", f"{_GATEWAY}.content_refusal"): "edge:gateway_final_refusal_record",
    edge(_PLAN, "enforce_inbound", f"{_GATEWAY}.content_refusal", 2): "edge:gateway_final_refusal_record",  # remedied
    edge(_PLAN, "enforce_inbound", f"{_GATEWAY}.tool_result_refusal"): "edge:gateway_final_refusal_record",
    edge(_OUTCOME, "GatewayOutcome", f"{_CONTRACT}.RequestBudget"): "app.services.content_routing.gateway_outcome",
    edge(_FINAL, "examine_request", f"{_CONTRACT}.examine_pass"): _FINAL,
    edge(_FINAL, "examine_request", f"{_CONTRACT}.examine_pass", 2): _FINAL,
    edge(_FINAL, "examine_request", f"{_CONTRACT}.compose"): _FINAL,
    edge(_REQUEST, "RequestExaminer.examine", f"{_CONTRACT}.examine", 2): _REQUEST,
    edge(_CALL, "_mask_output", f"{_CONTRACT}.RequestBudget"): _CALL,
    edge(_CALL, "_mask_output", f"{_CONTRACT}.compose"): _CALL,
    edge(_MODEL_CALL, "enforced_chat", f"{_CONTRACT}.RequestBudget"): _MODEL_CALL,
    edge(_OUTBOUND, "bound_constant", f"{_CONTRACT}.RequestBudget"): _OUTBOUND,
    **{edge(_CALL_OUTCOME, name, f"{_CONTRACT}.compose"): _CALL_OUTCOME
       for name in ("CallOutcome._sent", "_empty")},
    edge(_TOOL_RESULTS, "_decide", f"{_DECISION}.decide_tool_result"): _TOOL_RESULTS,
    edge(_TOOL_RESULTS, "_decide", f"{_DECISION}.scan_for"): _TOOL_RESULTS,
    edge(_TOOL_RESULTS, "_withheld.walk", f"{_CONTRACT}.examine_text"): _TOOL_RESULTS,
    edge(_CALL, "_mask_output", f"{_REQUEST}.RequestExaminer"): _CALL,
    edge("app.services.content_security.transport", "mask_run", f"{_REQUEST}.RequestExaminer"):
        "app.services.content_security.format_chat_messages",
    edge(_CALL, "enforce_call", f"{_REQUEST}.RequestExaminer"): _CALL,
    edge(_REQUEST, "RequestExaminer.examine", f"{_CONTRACT}.examine"): _REQUEST,
    edge(_REQUEST, "RequestExaminer.report", f"{_CONTRACT}.compose"): _REQUEST,
    edge(_FIELDS, "RecordedRun.completion", f"{_CONTRACT}.compose"): _FIELDS,
    edge(_FIELDS, "refusing", f"{_CONTRACT}.compose"): _FIELDS,
    edge(_FIELDS, "refusing", f"{_CONTRACT}.compose", 2): _FIELDS,
    edge(_FIELDS, "structure_examination", f"{_CONTRACT}.compose"): _FIELDS,
    edge(f"{_INBOUND}.codex_seat", "admit_codex_seat", f"{_SEAT_CONTENT}.seat_content_plan"): f"{_INBOUND}.codex_seat",
    edge(f"{_INBOUND}.openai_service", "handle_responses", f"{_SERVICE}.governed_plan"): f"{_INBOUND}.openai_service",
    edge(f"{_INBOUND}.seat", "_admitted_seat_request", f"{_SEAT_CONTENT}.seat_content_plan"): f"{_INBOUND}.seat",
    edge(f"{_INBOUND}.seat", "_company_call.plan_for", f"{_SEAT_CONTENT}.seat_content_plan"): f"{_INBOUND}.seat",
    edge(_SEAT_CONTENT, "seat_content_plan", f"{_PLAN}.enforce_inbound"): _SEAT_CONTENT,
    edge(_SERVICE, "content_plan", f"{_PLAN}.enforce_inbound"): _SERVICE,
    edge("app.services.security_analyzer.content_command", "content_command_analyzer", f"{_CONTRACT}.examine_text"):
        "app.services.security_analyzer.content_command",
    edge("app.tools.result_content", "_content_checked", f"{_TOOL_RESULTS}.check_tool_result"):
        "app.tools.result_content",
    edge("app.tools.result_content", "_mcp_content_checked", f"{_TOOL_RESULTS}.check_tool_result"):
        "app.tools.result_content",
    edge("octryx_claude.post_tool_use_hook", "run_post_tool_use", "octryx_claude.content_hooks.content_output"):
        "octryx_claude.post_tool_use_hook",
}
#: Interfaces whose every edge needs its own edge case (the module's case does not assert that result's use): the
#: decisions that act on the examination's findings never receive an unfinished one.
EDGE_ONLY = frozenset({f"{_GATEWAY}.handling_refusal", f"{_CLIENT_TOOLS}.client_tool_result_denial",
                       f"{_GATEWAY}.content_refusal", f"{_GATEWAY}.tool_result_refusal", f"{_SCAN}.secret_kinds"})


def _sources() -> dict[str, tuple[str, bool]]:
    sources = {}
    for root in ROOTS:
        for path in root.rglob("*.py"):
            if "static" in path.parts:
                continue
            parts = path.relative_to(root.parent).with_suffix("").parts
            package = parts[-1] == "__init__"
            sources[".".join(parts[:-1] if package else parts)] = (path.read_text(encoding="utf-8"), package)
    return sources


def test_no_scanner_use_bypasses_the_examination_contract_and_every_consumer_is_listed():
    found = sites(_sources())
    assert found["violations"] == {}
    assert frozenset(found["consumers"]) == CONSUMERS, "a new consumer needs a property case"
    assert frozenset(CASES) == CONSUMERS


def test_every_result_consuming_edge_is_listed_with_a_case():
    found = sites(_sources())
    assert found["edges"] == sorted(EDGES), "a new use site of a consumed interface needs a case"
    assert set(EDGES.values()) <= set(CASES) | set(EDGE_CASES)
    assert set(EDGE_CASES) <= set(EDGES.values()), "every edge case asserts a listed edge"
    for key, case in EDGES.items():
        interface = key.split(" -> ")[1].split(" #")[0]
        assert (interface not in EDGE_ONLY) or case in EDGE_CASES, f"{key} needs its own edge case"


PACKAGE = "app.services.content_detection"
SCANNER_SOURCE = "def scan(segments): ...\nclass ScanReport: ...\n"


def _found(**modules: str) -> dict:
    sources = {PACKAGE: ("", True), f"{PACKAGE}.scanner": (SCANNER_SOURCE, False)}
    sources.update({f"app.services.probe.{name}": (text, False) for name, text in modules.items()})
    sources["app.services.probe"] = ("", True)
    return sites(sources)


@pytest.mark.parametrize("source", [
    "from app.services.content_detection.scanner import scan\nscan([])\n",
    "from app.services.content_detection import scanner\nscanner.scan([])\n",
    "import app.services.content_detection\napp.services.content_detection.scanner.scan([])\n",
    "import app.services.content_detection.scanner as s\ns.scan([])\n",
    "from ..content_detection import scanner as s\nrun = s.scan\nrun([])\n",
    "from app.services import content_detection\nhandler = content_detection.scanner.scan\n",
    "from app.services.content_detection import scanner\nrun = getattr(scanner, 'scan')\n",
    "from app.services.content_detection.scanner import ScanReport\nR = ScanReport\nR()\n",
    "import importlib\nimportlib.import_module('app.services.content_detection.scanner')\n",
    "def check(report):\n    return report.unfinished\n",
    "def check(report):\n    return getattr(report, 'unfinished')\n",
])
def test_every_use_form_is_a_violation(source):
    assert "app.services.probe.user" in _found(user=source)["violations"]


def test_a_package_rebinding_is_followed_to_the_scanner():
    sources = {PACKAGE: ("from .scanner import scan\n", True), f"{PACKAGE}.scanner": (SCANNER_SOURCE, False),
               "app.services.probe": ("", True),
               "app.services.probe.user": ("from app.services.content_detection import scan\nscan([])\n", False),
               "app.services.probe.relay": ("from app.services.probe.user import scan as again\n", False)}
    violations = sites(sources)["violations"]
    assert {"app.services.probe.user", "app.services.probe.relay"} <= set(violations)


@pytest.mark.parametrize(("source", "consumer"), [
    ("from app.services.content_security.format_request_body import examine_request_body\n", True),
    ("from app.services.content_routing import gateway\ngateway.handling_refusal\n", True),
    ("from app.services.content_routing import client_tool_results as c\nc.launcher_tool_result\n", True),
    ("import app.services.content_detection.examination as e\ne.examine\n", True),
    ("from app.services.content_routing.gateway import DENIED_HINT\n", False)
])
def test_a_module_using_a_consumed_interface_is_a_consumer(source, consumer):
    assert ("app.services.probe.user" in _found(user=source)["consumers"]) is consumer


def test_a_launcher_module_reading_the_disposition_is_a_consumer():
    sources = {"octryx_claude": ("", True),
               "octryx_claude.reader": ("def read(content):\n    return content.get('updated_output')\n", False),
               "octryx_claude.other": ("def read(content):\n    return content.get('state')\n", False)}
    assert sites(sources)["consumers"] == ["octryx_claude.reader"]


def _consumer_sources(user: str) -> dict[str, tuple[str, bool]]:
    return {"app.services.content_routing": ("", True),
            "app.services.content_routing.gateway": ("def handling_refusal(): ...\n", False),
            "app.services.probe": ("", True), "app.services.probe.user": (user, False)}


ONE_SITE = ("from app.services.content_routing.gateway import handling_refusal\n"
            "def plan():\n    return handling_refusal()\n")
HANDLING = "app.services.content_routing.gateway.handling_refusal"


@pytest.mark.parametrize(("source", "extra"), [
    (ONE_SITE + "def again():\n    return handling_refusal()\n",
     edge("app.services.probe.user", "again", HANDLING)),
    (ONE_SITE + "def plan_twice():\n    handling_refusal()\n    handling_refusal()\n",
     edge("app.services.probe.user", "plan_twice", HANDLING, 2)),
    (ONE_SITE + "class Relay:\n    def run(self):\n        handler = handling_refusal\n        return handler\n",
     edge("app.services.probe.user", "Relay.run", HANDLING)),
])
def test_a_second_use_site_in_an_already_listed_module_is_a_new_edge(source, extra):
    listed = sites(_consumer_sources(ONE_SITE))
    assert listed["consumers"] == ["app.services.probe.user"]
    assert listed["edges"] == [edge("app.services.probe.user", "plan", HANDLING)]
    found = sites(_consumer_sources(source))
    assert found["consumers"] == listed["consumers"], "module membership alone does not change"
    assert extra in found["edges"] and len(found["edges"]) > len(listed["edges"])


def test_an_annotation_import_or_constant_is_not_a_result_consuming_edge():
    source = ("from app.services.content_routing.gateway import handling_refusal, LIMIT\n"
              "def typed(handler: handling_refusal) -> handling_refusal:\n    return LIMIT\n")
    assert sites(_consumer_sources(source))["edges"] == []


GROUPING = "app.services.content_security.format_request_body.GatewayScan.secret_kinds"
HOLDER = ("from app.services.content_security.format_request_body import examine_request_body\n"
          "def plan(body):\n    return examine_request_body(body).secret_kinds()\n")


def test_a_result_method_called_where_the_result_is_held_is_an_edge():
    sources = {"app.services.content_security": ("", True),
               "app.services.content_security.format_request_body": ("def examine_request_body(body): ...\n", False),
               "app.services.probe": ("", True)}
    listed = sites({**sources, "app.services.probe.user": (HOLDER, False)})
    assert edge("app.services.probe.user", "plan", GROUPING) in listed["edges"]
    again = HOLDER + "def regroup(scanned):\n    return scanned.secret_kinds()\n"
    found = sites({**sources, "app.services.probe.user": (again, False)})
    assert edge("app.services.probe.user", "regroup", GROUPING) in found["edges"], "a second consumption is new"
    # A module that never holds the result: an attribute of the same name is not that method.
    other = "def turn(env):\n    return env.secret_kinds()\n"
    assert sites({**sources, "app.services.probe.user": (other, False)})["edges"] == []
