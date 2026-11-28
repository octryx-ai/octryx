"""An answer built on this turn's tool evidence cites it with openable links."""

from __future__ import annotations

from app.services.answer_evidence.check import (
    REFUSAL_REASON_INVENTED_URL,
    REFUSAL_REASON_UNCITED,
    check_answer_evidence,
)
from app.services.answer_evidence.evidence import collect_turn_evidence
from tests.answer_evidence_guard_support import CITED_PETCLINIC, PETCLINIC_OWNER, UNCITED_PETCLINIC, _web_fetch_result

GUIDE = "https://github.com/spring-projects/spring-boot/wiki/Spring-Boot-4.0-Migration-Guide"


def _knowledge_changes_result() -> dict:
    return {
        "tool_name": "knowledge_changes",
        "params": {"product": "spring-boot", "to_version": "4.0"},
        "result": {
            "state": "ok",
            "product": "spring-boot",
            "facts": [
                {"kind": "REQUIRES", "fact": "Spring Boot 4.0 requires Java 17 or later", "version": "4.0", "source": "S1"},
                {"kind": "REQUIRES", "fact": "Spring Boot 4.0 requires Jakarta EE 11", "version": "4.0", "source": "S1"},
                {"kind": "REMOVES", "fact": "Undertow support was removed", "version": "4.0", "source": "S2"},
            ],
            "sources": [
                {"id": "S1", "cite_as": f"[Spring Boot 4.0 Migration Guide § Review System Requirements]({GUIDE}#review-system-requirements)"},
                {"id": "S2", "cite_as": f"[Spring Boot 4.0 Migration Guide § Removed Features]({GUIDE}#removed-features)"},
            ],
        },
    }


A1_ANSWER = f"""## Wichtigste Änderungen von Spring Boot 3 auf Spring Boot 4

Die Workspace-Knowledge nennt diese Änderungen:

### Systemanforderungen
- **Java 17**: Spring Boot 4.0 setzt mindestens Java 17 voraus ([Spring Boot 4.0 Migration Guide § Review System Requirements]({GUIDE}#review-system-requirements)).
- **Jakarta EE 11**: Spring Boot 4.0 basiert auf Jakarta EE 11 ([Spring Boot 4.0 Migration Guide § Review System Requirements]({GUIDE}#review-system-requirements)).

### Entfernte Funktionen
- **Undertow**: Die Unterstützung für Undertow wurde in Spring Boot 4.0 entfernt ([Spring Boot 4.0 Migration Guide § Removed Features]({GUIDE}#removed-features)).

**Quellen**
- [Spring Boot 4.0 Migration Guide § Review System Requirements]({GUIDE}#review-system-requirements)
- [Spring Boot 4.0 Migration Guide § Removed Features]({GUIDE}#removed-features)
"""


def test_an_answer_citing_a_url_from_the_turns_tool_results_passes() -> None:
    check = check_answer_evidence(CITED_PETCLINIC, collect_turn_evidence([_web_fetch_result()]))
    assert check.evidence_bearing and check.satisfied
    assert (check.cited_count, check.uncited_count, check.invented_urls) == (1, 0, ())


def test_the_a1_golden_answer_with_migration_guide_links_passes() -> None:
    check = check_answer_evidence(A1_ANSWER, collect_turn_evidence([_knowledge_changes_result()]))
    assert check.satisfied, check
    # Headings and the introduction ending with ":" are not statements; the source lines are cited.
    assert (check.cited_count, check.uncited_count, check.invented_urls) == (5, 0, ())
    # Two sections of one page: two citable sources, one openable page.
    assert check.evidence_url_count == 1
    assert len(collect_turn_evidence([_knowledge_changes_result()]).linkable) == 2


def test_the_a3_answer_with_facts_and_no_links_fails() -> None:
    check = check_answer_evidence(UNCITED_PETCLINIC, collect_turn_evidence([_web_fetch_result()]))
    assert not check.satisfied
    assert (check.cited_count, check.uncited_count) == (0, 2)
    assert check.refusal_reason == REFUSAL_REASON_UNCITED


def test_an_invented_url_fails_even_when_every_statement_has_a_link() -> None:
    answer = CITED_PETCLINIC + "\nThe visit list is ordered by date ([Visit.java](https://github.com/example/Visit.java)).\n"
    check = check_answer_evidence(answer, collect_turn_evidence([_web_fetch_result()]))
    assert not check.satisfied
    assert check.invented_urls == ("https://github.com/example/Visit.java",)
    assert check.refusal_reason == REFUSAL_REASON_INVENTED_URL


def test_a_greeting_without_evidence_is_unsourced_and_not_affected() -> None:
    check = check_answer_evidence("Hello! How can I help you today?", collect_turn_evidence([]))
    assert not check.evidence_bearing and check.satisfied


def test_a_citation_without_the_fragment_and_a_plain_label_are_citations() -> None:
    evidence = collect_turn_evidence(
        [
            _knowledge_changes_result(),
            {"tool_name": "knowledge_read", "result": {"state": "ok", "source_url": None, "cite_as": "Ops Runbook (no link)"}},
        ]
    )
    answer = (
        f"Spring Boot 4.0 requires Java 17 or later, see [the guide]({GUIDE}).\n\n"
        "The failover drill runs every quarter from Geneva, per Ops Runbook (no link).\n"
    )
    assert check_answer_evidence(answer, evidence).satisfied


def test_failed_tool_results_carry_no_evidence() -> None:
    failed = {"tool_name": "web_fetch", "result": {"error": "Fetch failed", "source_url": PETCLINIC_OWNER}}
    assert not collect_turn_evidence([failed]).evidence_bearing
