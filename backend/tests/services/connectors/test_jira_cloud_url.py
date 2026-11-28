"""A Jira Cloud connection saved as https://your-site.atlassian.net/jira (the browser address) would test "ok"
while every REST call goes to …/jira/rest/api/3/… and answers 404. Such a URL is refused, never rewritten."""

import pytest

from app.services.connector_auth.atlassian_modes import CODE_JIRA_CLOUD_URL_WITH_PATH, AtlassianAuthConfigError
from app.services.connector_auth.atlassian_validation import jira_cloud_url_problem, validate_auth_config


def test_a_jira_cloud_url_with_a_path_is_a_problem_and_the_site_root_is_not():
    assert jira_cloud_url_problem("https://your-site.atlassian.net/jira")
    assert jira_cloud_url_problem("https://your-site.atlassian.net/") is None
    assert jira_cloud_url_problem("https://jira.example.com/jira") is None  # Data Center keeps its context path


def test_saving_the_browser_address_is_refused():
    with pytest.raises(AtlassianAuthConfigError) as refused:
        validate_auth_config("jira", {"jira_url": "https://your-site.atlassian.net/jira"})
    assert refused.value.code == CODE_JIRA_CLOUD_URL_WITH_PATH
