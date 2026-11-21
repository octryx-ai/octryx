import app.services.request_analysis as request_analysis_package
import app.services.request_analysis.service as request_analysis_service
from app.services.request_analysis import contract, limits
from app.services.request_analysis.contract import build_request_analysis_contract_message
from app.services.request_analysis.limits import effective_limit_from_request_analysis, sanitize_implicit_limit_params
from app.services.request_analysis.service import build_request_analysis, required_summary_tools_from_request_analysis

_WEEKLY_SUMMARY = "erstelle mir eine Wochenszusammenfassung von änderungen in jira bitbucekt und confluence"


def _summary_analysis() -> dict:
    return build_request_analysis(
        _WEEKLY_SUMMARY,
        route_reason="summary_aggregation",
        context_domains=["jira", "bitbucket", "confluence"],
        required_domains=["jira", "bitbucket", "confluence"],
        enforce_domain_coverage=True,
    )


def test_request_analysis_takes_coverage_domains_from_the_explicit_context_plan():
    analysis = _summary_analysis()

    assert analysis["analysis_first"] is True
    assert analysis["required_domains"] == ["bitbucket", "confluence", "jira"]
    assert analysis["explicit_limit_requested"] is False
    # No prompt-keyword fields.
    for field in ("summary_request", "evidence_axes", "evidence_plan", "bounded_evidence_request"):
        assert field not in analysis


def test_the_prompt_adds_no_domain_and_no_coverage():
    analysis = build_request_analysis(
        "Summarize the Jira, Bitbucket and AWS EKS changes: overview, functions and architecture.",
        route_reason="contextual_request",
    )

    assert analysis["requested_domains"] == []
    assert analysis["required_domains"] == []
    assert analysis["analysis_first"] is False
    assert required_summary_tools_from_request_analysis(analysis) == set()


def test_effective_limit_from_request_analysis_uses_explicit_user_limit():
    limit = effective_limit_from_request_analysis(
        snapshot=None,
        fallback_user_message="check only 10 pages in confluence",
        requested_limit=None,
        default_if_unspecified=1000,
        hard_max=1000,
    )

    assert limit == 10


def test_required_summary_tools_include_all_explicit_coverage_domains():
    tools = required_summary_tools_from_request_analysis(_summary_analysis())

    assert "search_jira_tickets" in tools
    assert "list_recent_bitbucket_commits" in tools
    assert "search_confluence" in tools


def test_sanitize_implicit_limit_params_removes_model_default_limits_when_user_did_not_request_any():
    snapshot = {"request_analysis": _summary_analysis()}

    cleaned = sanitize_implicit_limit_params(
        tool_name="search_confluence",
        params={"limit": 25, "space_key": "RIVER"},
        snapshot=snapshot,
        fallback_user_message=None,
    )

    assert cleaned == {"space_key": "RIVER"}


def test_sanitize_implicit_limit_params_covers_neighbor_read_tools():
    snapshot = {"request_analysis": _summary_analysis()}

    assert sanitize_implicit_limit_params(
        tool_name="search_confluence",
        params={"limit": 10, "query": "acme-orders"},
        snapshot=snapshot,
    ) == {"query": "acme-orders"}
    assert sanitize_implicit_limit_params(
        tool_name="get_project_knowledge_overview",
        params={"limit": 20, "project_id": "p1"},
        snapshot=snapshot,
    ) == {"project_id": "p1"}
    assert sanitize_implicit_limit_params(
        tool_name="list_workspace_git_commits",
        params={"limit": 25, "days": 7},
        snapshot=snapshot,
    ) == {"days": 7}
    assert sanitize_implicit_limit_params(
        tool_name="load_tool_artifact",
        params={"artifact_id": "a1", "max_items": 20},
        snapshot=snapshot,
    ) == {"artifact_id": "a1"}
    assert sanitize_implicit_limit_params(
        tool_name="list_monitors",
        params={"limit": 20, "query": "cpu"},
        snapshot=snapshot,
    ) == {"query": "cpu"}


def test_the_execution_contract_lists_the_explicit_coverage_domains():
    contract = build_request_analysis_contract_message(_summary_analysis())

    assert "Required domains: bitbucket, confluence, jira." in contract
    assert "Evidence axes" not in contract


def test_request_analysis_package_exports_its_service() -> None:
    assert (
        request_analysis_package.build_request_analysis
        is request_analysis_service.build_request_analysis
    )
    assert (
        request_analysis_package.build_request_analysis_contract_message
        is contract.build_request_analysis_contract_message
    )
    assert (
        request_analysis_package.effective_limit_from_request_analysis
        is limits.effective_limit_from_request_analysis
    )
