"""Request analysis allowlists and language contracts, tool status and artifact-ready messages."""

from app.services.request_analysis.service import build_request_analysis


def test_request_analysis_leaves_the_language_to_the_model():
    message = "Erstelle mir eine Wochenzusammenfassung von Änderungen in Jira, Bitbucket und Confluence"
    analysis = build_request_analysis(
        message,
        route_reason="summary_aggregation",
        required_domains=["jira", "bitbucket", "confluence"],
        context_domains=["jira", "bitbucket", "confluence"],
        enforce_domain_coverage=True,
    )

    assert analysis["language_contract"]["output_language"] == "the language of the user's message"
    assert analysis["canonical_message"] == message  # no translation or rewriting of the user's words
    assert "summary_request" not in analysis  # No prompt-keyword summary intent








