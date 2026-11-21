from app.tools.runtime_impl import _runtime_cli_helpers as helpers


def test_normalize_domain_token_strips_scheme_www_and_trailing_dot():
    assert helpers._normalize_domain_token("https://www.Example.com./path") == "example.com"


def test_search_result_allowed_respects_domain_term_and_preprint_filters():
    assert not helpers._search_result_allowed(
        {
            "title": "Working paper on platform design",
            "snippet": "Preview paper from arXiv",
            "url": "https://sub.arxiv.org/abs/1234",
        },
        include_domains=["example.com"],
        exclude_domains=[],
        exclude_terms=["forbidden phrase"],
        exclude_preprints=True,
    )
    assert not helpers._search_result_allowed(
        {
            "title": "Allowed title",
            "snippet": "Contains forbidden phrase in snippet",
            "url": "https://docs.example.com/post",
        },
        include_domains=["example.com"],
        exclude_domains=[],
        exclude_terms=["forbidden phrase"],
        exclude_preprints=False,
    )
    assert helpers._search_result_allowed(
        {
            "title": "Allowed title",
            "snippet": "Regular documentation",
            "url": "https://docs.example.com/post",
        },
        include_domains=["example.com"],
        exclude_domains=["blocked.com"],
        exclude_terms=["forbidden phrase"],
        exclude_preprints=True,
    )


def test_apply_search_query_filters_adds_domain_and_term_clauses():
    assert helpers._apply_search_query_filters(
        "enterprise agents",
        include_domains=["docs.example.com"],
        exclude_domains=["blog.example.com"],
        exclude_terms=["working paper", "draft"],
        exclude_preprints=True,
    ) == (
        "enterprise agents site:docs.example.com -site:blog.example.com "
        '-site:arxiv.org -site:ssrn.com -preprint -"working paper" -"preview paper" '
        '-"working paper" -draft'
    )
