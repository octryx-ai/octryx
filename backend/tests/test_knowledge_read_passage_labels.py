"""knowledge_read labels each passage of a window with its own evidence key (research citation precision)."""
from app.services.knowledge.ledger.reading import SpanWindow
from app.tools.knowledge_evidence.read import labelled_text


def _window(passages):
    return SpanWindow(evidence_key=passages[0][0], text="\n\n".join(t for _, t in passages), citation="c",
                      source_title="t", source_url=None, revision_ordinal=1, current=True, first_span=1,
                      last_span=len(passages), passages=tuple(passages))


def test_a_window_labels_every_passage_with_its_key():
    text = labelled_text(_window([("a" * 32 + ":1", "What"), ("a" * 32 + ":2", "How to use")]))
    assert text == f"[{'a' * 32}:1]\nWhat\n\n[{'a' * 32}:2]\nHow to use"


def test_a_single_passage_stays_unlabelled():
    assert labelled_text(_window([("a" * 32 + ":1", "What")])) == "What"
