"""Credible research sources need authoritative technical markers."""

from app.services.research_source_quality import research_source_is_credible


def test_research_source_is_credible_requires_authoritative_technical_sources():
    topic = "ticketing API integration"

    assert research_source_is_credible(
        topic=topic,
        title="Ticketing API Integration Reference",
        url="https://developer.example.com/ticketing-api-integration",
        snippet="Official developer documentation for REST API endpoints and webhook setup.",
    )
    assert not research_source_is_credible(
        topic=topic,
        title="Decoding Ticketing Integration",
        url="https://blog-a.example/blog/ticketing-api-integration-all-you-need-to-know",
        snippet="A blog post with best practices and platform overview.",
    )
    assert not research_source_is_credible(
        topic=topic,
        title="Published February 9, 2026",
        url=("https://blog-c.example/blog/"
             "ticketing_api_integration_tickets_customers_notes_and_categories_across_support_platforms"),
        snippet="Marketing blog post about unified ticketing integrations.",
    )
    assert not research_source_is_credible(
        topic=topic,
        title="01/06/2026",
        url="https://blog-b.example/ticketing-api-integration-use-cases-best-practices/",
        snippet="Generic article about use cases and best practices.",
    )
