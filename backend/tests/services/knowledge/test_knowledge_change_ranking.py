"""A changes page leads with what an upgrade hinges on, decided by document structure (Knowledge, A1)."""

from __future__ import annotations

from dataclasses import dataclass

from app.services.knowledge.temporal.change_ranking import distinct, rank_tier


@dataclass(frozen=True)
class Citation:
    revision_id: str
    source_id: str
    span_ordinal: int
    section_path: tuple[str, ...]


@dataclass(frozen=True)
class Fact:
    relation: str
    fact: str
    citation: Citation


def _fact(doc: str, span: int, section: str, text: str, relation: str = "REQUIRES") -> Fact:
    return Fact(relation, text, Citation(f"rev-{doc}", f"src-{doc}", span, (section,)))


ROLES = {"src-guide": "migration_guide", "src-notes": "release_notes", "src-config": "configuration_changelog"}


def test_guides_and_notes_lead_and_the_configuration_changelog_follows():
    config = [_fact("config", span, f"property {span}", f"property {span} renamed") for span in range(1, 40)]
    guide = [
        _fact("guide", 2, "System Requirements", "Spring Boot 4.0 requires Java 17 or later"),
        _fact("guide", 9, "Web Servers", "Undertow support is dropped", "REMOVED"),
    ]
    notes = [_fact("notes", 4, "Dependency Upgrades", "Spring Boot 4.0 updates Jackson to 3.0")]
    page = rank_tier(config + notes + guide, ROLES, lambda kind: 0)[:5]
    assert [item.fact for item in page[:3]] == [
        "Spring Boot 4.0 requires Java 17 or later",
        "Spring Boot 4.0 updates Jackson to 3.0",
        "Undertow support is dropped",
    ]
    assert all(item.citation.source_id == "src-config" for item in page[3:])


def test_leaf_sections_take_turns_so_system_requirements_are_not_buried():
    def at(span, path, text):
        return Fact("REQUIRES", text, Citation("rev-guide", "src-guide", span, path))

    start = ("Guide", "Before You Start")
    facts = [
        at(1, (*start, "Upgrade to 3.5.x"), "upgrade to 3.5.x first"),
        at(2, (*start, "Review Dependencies"), "review dependency management"),
        at(3, (*start, "Review System Requirements"), "requires Java 17 or later"),
        at(4, (*start, "Upgrade to 3.5.x"), "another 3.5.x note"),
    ]
    assert [item.fact for item in rank_tier(facts, ROLES, lambda kind: 0)][:3] == [
        "upgrade to 3.5.x first",
        "review dependency management",
        "requires Java 17 or later",
    ]


def test_sections_are_read_in_turns_and_duplicates_are_shown_once():
    long_section = [_fact("guide", span, "Jackson", f"jackson change {span}") for span in range(10, 20)]
    other = _fact("guide", 30, "Starters", "Starters are split into modules")
    ranked = rank_tier(long_section + [other], ROLES, lambda kind: 0)
    assert ranked[1].fact == "Starters are split into modules"
    twice = [
        _fact("guide", 1, "A", "Undertow support is dropped"),
        _fact("notes", 5, "B", "undertow  support is DROPPED"),
        _fact("config", 7, "C", "Undertow support is dropped."),
    ]
    assert len(distinct(twice)) == 1


@dataclass(frozen=True)
class EntityFact:
    relation: str
    fact: str
    source_entity: str
    citation: Citation


def test_product_baselines_of_one_section_take_turns_with_the_other_changes():
    from app.services.knowledge.temporal.change_ranking import is_product_level

    def at(span, section, subject, text, relation="REQUIRES"):
        return EntityFact(relation, text, subject, Citation("rev-guide", "src-guide", span, ("Guide", section)))

    requirements = [
        at(4, "Review System Requirements", "Spring Boot 4.0", "Spring Boot 4.0 requires Java 17"),
        at(4, "Review System Requirements", "Spring Boot 4.0", "Spring Boot 4.0 requires Spring Framework 7"),
        at(20, "Dependency Upgrades", "Spring Boot 4.0", "Spring Boot 4.0 updates Liquibase to 5.0"),
    ]
    removals = [at(10 + n, f"Module {n}", f"Module {n}", f"module {n} is removed", "REMOVED") for n in range(6)]
    page = rank_tier(removals + requirements, ROLES, lambda kind: 0, is_product_level("spring-boot"))[:4]
    assert page[0].fact == "Spring Boot 4.0 requires Java 17"

    assert {item.fact for item in page[::2]} == {
        "Spring Boot 4.0 requires Java 17",
        "Spring Boot 4.0 requires Spring Framework 7",
    }
    assert all(item.relation == "REMOVED" for item in page[1::2])
    assert not is_product_level("spring-boot")(at(1, "A", "Spring Bootstrap", "x"))


@dataclass(frozen=True)
class TimedFact:
    relation: str
    fact: str
    source_entity: str
    citation: Citation
    extracted_at: str


def test_baselines_of_one_span_keep_the_order_they_were_extracted_in():
    from app.services.knowledge.temporal.change_ranking import is_product_level

    def at(stamp, text):
        citation = Citation("rev-guide", "src-guide", 4, ("Guide", "Review System Requirements"))
        return TimedFact("REQUIRES", text, "Spring Boot 4.0", citation, stamp)

    facts = [at("07:27:17.2025", "requires Spring Framework 7"), at("07:27:17.2021", "requires Java 17"),
             at("07:27:17.2023", "is based on Jakarta EE 11")]
    ranked = rank_tier(facts, ROLES, lambda kind: 0, is_product_level("spring-boot"))
    assert [item.fact for item in ranked] == ["requires Java 17", "is based on Jakarta EE 11", "requires Spring Framework 7"]
