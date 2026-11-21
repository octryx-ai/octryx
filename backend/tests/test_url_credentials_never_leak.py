"""Credentials in a remote URL never reach a log, an event or an error text.

Every scrubber that prints remote URLs gets the same inputs: a token as user name (``https://<token>@github.com``, the
usual Git token form, easy for a redaction to miss), user and password, a password with an
``@``, a percent-encoded one, and several URLs in one error text."""

import pytest

from app.services.outbound_webhook.serialization import _mask_url
from app.services.redaction_policy import redact_embedded_credentials, redact_secret_text
from app.services.source_control.contracts import _redact_url_credentials
from app.services.workflow_runs.workspace.recovery import _refused, _scrubbed
from app.tools.bitbucket_impl._bitbucket_internal_core import _mask_clone_url

SECRET = "S3cr3tT0k3n"
URLS = {
    "token as user": f"https://{SECRET}@github.com/acme/repo.git",
    "bitbucket token user": f"https://x-token-auth:{SECRET}@bitbucket.org/acme/repo.git",
    "user and password": f"https://alice:{SECRET}@github.com/acme/repo.git",
    "@ in the password": f"https://alice:{SECRET}@x@gitlab.com/acme/repo.git",
    "percent-encoded": f"https://alice:{SECRET}%40x@host.example/repo.git",
}
TEXTS = {
    **{f"git error with {k}": f"fatal: unable to access '{u}/': The requested URL returned error: 403"
       for k, u in URLS.items()},
    "two urls": f"from https://a:{SECRET}@h1.example/r.git to https://{SECRET}@h2.example/r.git",
}

TEXT_SCRUBBERS = {
    "workspace recovery": _scrubbed,
    "workspace recovery report": lambda text: str(_refused(text)),
    "central redaction": lambda text: redact_embedded_credentials(text)[0],
    "secret text redaction": redact_secret_text,
}
URL_SCRUBBERS = {
    "source control contract": _redact_url_credentials,
    "bitbucket clone url": _mask_clone_url,
    "outbound webhook url": _mask_url,
    **TEXT_SCRUBBERS,
}


@pytest.mark.parametrize("scrub", URL_SCRUBBERS.values(), ids=URL_SCRUBBERS.keys())
@pytest.mark.parametrize("url", URLS.values(), ids=URLS.keys())
def test_no_scrubbed_url_keeps_its_credential(scrub, url):
    assert SECRET not in scrub(url)


@pytest.mark.parametrize("scrub", TEXT_SCRUBBERS.values(), ids=TEXT_SCRUBBERS.keys())
@pytest.mark.parametrize("text", TEXTS.values(), ids=TEXTS.keys())
def test_no_scrubbed_error_text_keeps_a_credential(scrub, text):
    scrubbed = scrub(text)
    assert SECRET not in scrubbed
    assert "github.com" in scrubbed or "bitbucket.org" in scrubbed or ".example" in scrubbed or "gitlab" in scrubbed


def test_the_host_and_path_stay_readable():
    assert redact_embedded_credentials(URLS["token as user"])[0] == "https://[redacted]@github.com/acme/repo.git"
