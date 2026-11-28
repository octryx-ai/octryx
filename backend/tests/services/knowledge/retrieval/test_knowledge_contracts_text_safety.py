"""Text safety keeps meaningful text and line breaks only where allowed; retrieval errors stay explicit and caller-proof."""

from __future__ import annotations

import pytest

from app.services.knowledge.identity.workspace import WorkspaceId
from app.services.knowledge.retrieval.contracts import Evidence, RetrievalMode
from app.services.knowledge.retrieval.errors import (
    INDEX_MODES,
    InvalidRetrievalRequestError,
    InvalidWorkspaceError,
    KnowledgeIndexUnavailableError,
    KnowledgeRetrievalError,
    KnowledgeStoreContractError,
    KnowledgeStoreNotConfiguredError,
    RetrievalFailureState,
    WorkspaceRequiredError,
    WorkspaceScopeError,
)
from app.services.knowledge.text_safety import has_unsafe_chars, remove_unsafe_chars
from tests.services.knowledge.retrieval.knowledge_contracts_support import WS, _request

# Variation selectors (both ranges, both ends), Hangul fillers, noncharacters
# (U+FDD0-U+FDEF and code points ending FFFE/FFFF), and private use (Co).
BLANK_OR_MEANINGLESS_CHARS = [
    "\ufe00",
    "\ufe0f",
    "\U000e0100",
    "\U000e01ef",
    "\u115f",
    "\u1160",
    "\u3164",
    "\uffa0",
    "\ufdd0",
    "\ufdef",
    "\ufffe",
    "\uffff",
    "\U0001fffe",
    "\U0010ffff",
    "\ue000",
    "\uf8ff",
    "\U000f0000",
    "\U0010fffd",
]


# Letters and combining marks of several scripts, including a decomposed accent.
INTERNATIONAL_TEXT = "Café cafe\u0301 Straße Ελληνικά Кириллица العربية עברית हिन्दी ไทย 한국어 日本語 中文"


# --- Text safety -------------------------------------------------------------------


@pytest.mark.parametrize("char", BLANK_OR_MEANINGLESS_CHARS)
def test_text_safety_rejects_blank_and_meaningless_characters(char):
    assert has_unsafe_chars(f"a{char}b", allow_line_breaks=True)
    assert remove_unsafe_chars(f"a{char}b", allow_line_breaks=True) == "ab"
    with pytest.raises(InvalidRetrievalRequestError) as exc_info:
        _request(query_text=f"orders{char}service")
    assert str(exc_info.value) == InvalidRetrievalRequestError.default_message
    workspace = WorkspaceId.parse(WS)
    with pytest.raises(InvalidRetrievalRequestError):
        Evidence(workspace=workspace, evidence_id="c1", mode="vector", kind="passage", text=f"a{char}b")
    with pytest.raises(InvalidRetrievalRequestError):
        Evidence(workspace=workspace, evidence_id="c1", mode="vector", kind="passage", text="t", citation=f"a{char}")


@pytest.mark.parametrize("char", ["\ufdcf", "\ufdf0", "\ufdfd", "\ufe10", "\ufffd", "\U000e00ff", "\U000e01f0"])
def test_text_safety_keeps_neighbours_of_rejected_ranges(char):
    assert not has_unsafe_chars(f"a{char}b", allow_line_breaks=False)


def test_text_safety_keeps_international_letters_and_combining_marks():
    assert not has_unsafe_chars(INTERNATIONAL_TEXT, allow_line_breaks=False)
    assert remove_unsafe_chars(INTERNATIONAL_TEXT, allow_line_breaks=False) == INTERNATIONAL_TEXT
    assert _request(query_text=INTERNATIONAL_TEXT).query_text == INTERNATIONAL_TEXT
    body = f"{INTERNATIONAL_TEXT}\r\n\t{INTERNATIONAL_TEXT}"
    item = Evidence(
        workspace=WorkspaceId.parse(WS),
        evidence_id="c1",
        mode="vector",
        kind="passage",
        text=body,
        citation=INTERNATIONAL_TEXT,
    )
    assert item.text == body and item.citation == INTERNATIONAL_TEXT


def test_text_safety_line_breaks_only_where_allowed():
    assert not has_unsafe_chars("a\tb\nc\rd", allow_line_breaks=True)
    assert all(has_unsafe_chars(char, allow_line_breaks=False) for char in "\t\n\r")
    assert remove_unsafe_chars("a\tb\n", allow_line_breaks=False) == "ab"


def test_error_states_are_explicit():
    assert KnowledgeStoreNotConfiguredError().state is RetrievalFailureState.NEEDS_CONFIGURATION
    unavailable = KnowledgeIndexUnavailableError(RetrievalMode.GRAPH)
    assert unavailable.state is RetrievalFailureState.UNAVAILABLE
    assert unavailable.mode == "graph" and type(unavailable.mode) is str
    assert str(unavailable) == KnowledgeIndexUnavailableError.default_message


def test_index_modes_match_retrieval_modes():
    assert {mode.value for mode in RetrievalMode} == INDEX_MODES


@pytest.mark.parametrize("mode", ["cypher", "VECTOR", "", None, 1, RetrievalMode])
def test_unavailable_error_rejects_unknown_modes(mode):
    with pytest.raises(ValueError) as exc_info:
        KnowledgeIndexUnavailableError(mode)
    assert "cypher" not in str(exc_info.value)


@pytest.mark.parametrize(
    "error_class",
    [
        KnowledgeRetrievalError,
        WorkspaceScopeError,
        WorkspaceRequiredError,
        InvalidWorkspaceError,
        InvalidRetrievalRequestError,
        KnowledgeStoreNotConfiguredError,
        KnowledgeStoreContractError,
    ],
)
def test_error_messages_cannot_be_supplied_by_callers(error_class):
    with pytest.raises(TypeError):
        error_class("SELECT * FROM secrets WHERE token = 'x'")
    assert str(error_class()) == error_class.default_message


def test_unavailable_error_message_cannot_be_supplied_by_callers():
    with pytest.raises(TypeError):
        KnowledgeIndexUnavailableError("graph", "SELECT * FROM secrets")  # type: ignore[call-arg]
