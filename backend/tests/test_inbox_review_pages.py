"""A review in the Inbox opens its own page (a prompt review must not open the decisions page)."""

from __future__ import annotations

from types import SimpleNamespace

from app.services.inbox.service import _review_page
from app.services.prompt_catalog.governance import publish_approval_action


def test_a_prompt_review_opens_the_prompt_catalog():
    action = publish_approval_action(SimpleNamespace(id="v-1", digest="sha256:abc"))
    assert _review_page(action) == ("promptCatalog", "Prompt")
    assert _review_page("something.else") == ("observabilityDecisions", "Review")
