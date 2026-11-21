"""Source credibility: low-signal and community sources are not credible; malformed titles are not citation quality."""

from app.services.research_source_quality import (
    research_source_title_is_citation_quality,
    research_url_is_credible,
)


def test_research_source_credibility_allows_official_pdfs_but_blocks_community_noise():
    topic = "ticketing API integration"

    assert research_url_is_credible(
        topic=topic,
        url="https://resources.docs.salesforce.com/latest/latest/en-us/sfdc/pdf/api_cti.pdf",
    )
    assert research_url_is_credible(
        topic=topic,
        url="https://www.tenable.com/sites/default/files/solution-briefs/TicketingIntegration_SB__EN__v6_web.pdf",
    )
    assert not research_url_is_credible(
        topic=topic,
        url="https://community.developer.atlassian.com/t/latest-jira-server-rest-api-documentation/49389",
    )


def test_research_source_metadata_helpers_reject_malformed_titles():
    assert not research_source_title_is_citation_quality("2026-04-12")
    assert not research_source_title_is_citation_quality("https://developer.example.com/docs/ticketing")
    assert not research_source_title_is_citation_quality("[Ticketing API](/docs/ticketing-api)")
    assert research_source_title_is_citation_quality("Ticketing API Integration Reference")
