"""A version change hits exactly the code elements its fact names.

Contract tests only: the checkout scan (elements, lines, the commit read without git), and the
join's exact-naming rules. The rules cover qualified names, CamelCase class names, package
prefixes, annotations, wildcard property prefixes, artifact ids and the Java baseline. They also
cover what must *not* match: prose words, and short class names that are ordinary words.
"""

from __future__ import annotations

from pathlib import Path

from app.services.knowledge.code.commit import checkout_commit
from app.services.knowledge.code.impact import KIND_BASELINE, join_impact
from app.services.knowledge.code.scan import scan_checkout
from app.services.knowledge.ledger.citations import ResolvedCitation
from app.services.knowledge.temporal.changes_facts import ChangeFact

SHA = "b26f235250627a235a2974a22f2317dbef27338d"


def _checkout(root: Path) -> Path:
    (root / ".git" / "refs" / "heads").mkdir(parents=True)
    (root / ".git" / "HEAD").write_text("ref: refs/heads/main\n")
    (root / ".git" / "packed-refs").write_text(f"# pack-refs\n{SHA} refs/heads/main\n")
    source = root / "src" / "main" / "java" / "demo"
    source.mkdir(parents=True)
    (source / "Json.java").write_text(
        "package demo;\n"
        "import org.springframework.boot.jackson.JsonComponent;\n"
        "import org.springframework.boot.jackson.JsonObjectSerializer;\n"
        "import javax.annotation.PostConstruct;\n"
        "import org.springframework.context.annotation.Bean;\n"
        "@JsonComponent\n"
        "class Json extends JsonObjectSerializer<Object> { @Bean Object bean() { return null; } }\n"
    )
    resources = root / "src" / "main" / "resources"
    resources.mkdir(parents=True)
    (resources / "application.yml").write_text("spring:\n  jackson:\n    parser:\n      allow-comments: true\n")
    (root / "pom.xml").write_text(
        "<project>\n  <properties>\n    <java.version>11</java.version>\n  </properties>\n"
        "  <dependencies>\n    <dependency><artifactId>spring-boot-starter-web</artifactId></dependency>\n"
        "  </dependencies>\n</project>\n"
    )
    (root / "target").mkdir()
    (root / "target" / "Generated.java").write_text("import javax.annotation.Generated;\n")
    return root


def _fact(text: str) -> ChangeFact:
    citation = ResolvedCitation(
        evidence_key="a" * 32 + ":1", citation="Guide (rev 1)", revision_id="r", span_ordinal=1,
        object_bucket="b", object_key="k", content_sha256="0" * 64, source_title="Guide",
        source_url="https://example.com/guide",
    )
    return ChangeFact("CHANGES", text, "", "", "4.0", citation, 1)


def test_the_scan_pins_the_commit_and_finds_each_element_at_its_line(tmp_path):
    root = _checkout(tmp_path)
    elements = scan_checkout(root)

    assert checkout_commit(root) == SHA
    found = {(e.kind, e.value, e.path, e.line) for e in elements}
    assert ("annotation", "JsonComponent", "src/main/java/demo/Json.java", 6) in found
    assert ("property", "spring.jackson.parser.allow-comments", "src/main/resources/application.yml", 4) in found
    assert ("dependency", "spring-boot-starter-web", "pom.xml", 6) in found
    assert any(e.kind == "build_property" and e.value == "java.version" and e.detail == "11" for e in elements)
    # Build output is never scanned.
    assert not any(e.path.startswith("target/") for e in elements)


def test_a_change_hits_exactly_the_elements_its_fact_names(tmp_path):
    elements = scan_checkout(_checkout(tmp_path))
    facts = (
        _fact("@JsonComponent has been renamed to @JacksonComponent"),
        _fact("JsonObjectSerializer has been renamed to ObjectValueSerializer"),
        _fact("spring.jackson.parser.* properties have been replaced with spring.jackson.json.read.*"),
        _fact("Spring Boot 4.0 requires Java 17 or later"),
        _fact("javax.annotation annotations are no longer supported, use jakarta.annotation"),
        _fact("spring-boot-starter-web has been renamed to spring-boot-starter-webmvc"),
        _fact("A Bean definition is no longer sufficient for Spring Boot"),
    )

    items = {item.fact.fact: item for item in join_impact(facts, elements)}

    def places(fact: str) -> set[tuple[str, int]]:
        return {(loc.path, loc.line) for loc in items[fact].locations}

    assert places(facts[0].fact) == {("src/main/java/demo/Json.java", 2), ("src/main/java/demo/Json.java", 6)}
    assert places(facts[1].fact) == {("src/main/java/demo/Json.java", 3)}
    assert places(facts[2].fact) == {("src/main/resources/application.yml", 4)}
    assert items[facts[3].fact].reason == KIND_BASELINE and places(facts[3].fact) == {("pom.xml", 3)}
    assert places(facts[4].fact) == {("src/main/java/demo/Json.java", 4)}
    assert places(facts[5].fact) == {("pom.xml", 6)}
    # "Bean" and "Spring Boot" are words here, not the @Bean annotation or an artifact: no item.
    assert facts[6].fact not in items
