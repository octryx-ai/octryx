"""Substantive cited answers must survive transition suppression."""

from app.agent.core.guards._response_guard_text import looks_like_repetitive_transition
from app.agent.core.guards.response_guards import is_transitional_assistant_response


def test_repeated_references_do_not_turn_an_answer_into_a_transition():
    reference = "[Source](https://github.com/example/project/blob/abcdef/src/Controller.java#L39-L90)."
    content = (
        "I'll provide the complete answer with proper citations from the evidence: "
        "The controller handles the creation endpoint. "
        f"{reference} {reference} "
        "GET displays the form; POST validates the submitted entity and either redisplays "
        "the form or redirects to the saved record. Each operation uses the same controller "
        "mapping, while the method annotation determines the HTTP verb. "
        f"{reference}"
    )
    assert not looks_like_repetitive_transition(content)
    assert not is_transitional_assistant_response(content, None, True)


def test_repeated_transition_announcements_still_stop():
    content = "I'll check the repository now. I'll check the repository now."
    assert looks_like_repetitive_transition(content)
    assert is_transitional_assistant_response(content, None, True)


def test_two_similar_internal_source_links_do_not_suppress_the_inspected_answer():
    base = (
        "/chat?area=coding&coding_view=repositories&workspace_id=785b4554-bfbc-41f6-9f39-d408868134b2"
        "&repository_id=b6d9ca89-bdd1-410c-8e0f-e999688dbad0&generation=" + "a" * 32 + "&symbol_id="
    )
    first = f"[src/main/java/owner/OwnerController.java L92-116]({base}284)"
    second = f"[src/main/java/owner/OwnerController.java L127-131]({base}286)"
    answer = (
        f"The handler searches owners and delegates pagination. {first}\n\n"
        f"The private helper creates a pageable request with five items and queries the repository. {second}"
    )
    assert not looks_like_repetitive_transition(answer)
    assert not is_transitional_assistant_response(answer, None, True)
    repeated = f"I'll check the repository now. {first} I'll check the repository now. {second}"
    assert looks_like_repetitive_transition(repeated)
    assert is_transitional_assistant_response(repeated, None, True)
