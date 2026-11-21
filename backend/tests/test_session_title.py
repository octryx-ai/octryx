"""Deterministic chat titles."""

from __future__ import annotations

import pytest

from app.services.session.session_title import (
    TITLE_MAX_CHARS,
    apply_prompt_title,
    apply_user_title,
    title_from_prompt,
)


@pytest.mark.parametrize(
    ("prompt", "title"),
    [
        (
            "can you help me plan the q4 hiring pipeline for the data team? we need two analysts",
            "Plan the q4 hiring pipeline for the data team",
        ),
        ("Hi, please summarise the vendor SLA comparison.", "Summarise the vendor SLA comparison"),
        ("hello there! could you please review the retention wording", "Review the retention wording"),
        ("Hey\nWhy does the export miss rows?", "Why does the export miss rows"),
        (
            "Fix this:\n```python\nprint('x')\n```",
            "Fix this",
        ),
        ("Check https://example.com/report?id=1 for broken links", "Check for broken links"),
        (
            "Inspect the files\n\nAttached workspace files:\n- a.pdf | path: /w/a.pdf (application/pdf, 10 bytes)",
            "Inspect the files",
        ),
        ("```\nonly code\n```", "New chat"),
        ("   ", "New chat"),
    ],
)
def test_title_from_prompt(prompt, title):
    assert title_from_prompt(prompt) == title


def test_a_long_first_sentence_is_cut_at_a_word_boundary():
    title = title_from_prompt(
        "Estimate the storage growth for the analytics cluster across all regions until the end of 2027"
    )

    assert len(title) <= TITLE_MAX_CHARS
    assert title == "Estimate the storage growth for the analytics cluster across"
    assert not title.endswith(" ")


def test_a_user_title_is_never_replaced_by_the_prompt_rule():
    metadata: dict = {}
    assert apply_user_title(metadata, "  My   budget chat ") is True
    apply_prompt_title(metadata, "Something else entirely")

    assert metadata == {"title": "My budget chat", "title_source": "user"}
    assert apply_user_title(metadata, "   ") is False


def test_the_prompt_rule_records_its_source():
    metadata: dict = {}
    apply_prompt_title(metadata, "please draft the incident timeline")

    assert metadata == {"title": "Draft the incident timeline", "title_source": "prompt"}
