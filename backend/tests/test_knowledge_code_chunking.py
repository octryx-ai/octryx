"""Code-aware spans and line-preserving redaction of repository files.

- Java (tree-sitter) and Python (ast) spans follow their symbols, a member's Javadoc, annotations or
  decorators included, with exact 1-based line ranges and character ranges that slice the text back;
- neighbouring members of one declaration merge into one span up to the merge bound, a member is
  never split by the merge, and the file preamble stays its own span;
- a file without a parser is windowed with overlap, and every window stays inside the span bound;
- redaction replaces secrets inside their lines and never changes the line count;
- a ``#L`` link is added to the origin URL, and a URL that already has a fragment is left alone.
"""

from __future__ import annotations

from app.services.knowledge.code.chunking import MERGE_MAX_LINES, OVERLAP_LINES, WINDOW_LINES, derive_code_spans
from app.services.knowledge.code.redaction import redact_repository_text
from app.services.knowledge.ingestion.spans import MAX_SPAN_CHARS
from app.services.knowledge.sources.source_url import line_link
from app.services.knowledge.sources.sync.git_paths import PathFilter, language_of

JAVA = """package demo;

import java.util.List;

/** An owner. */
@Entity
public class Owner {
    private String name;

    /** Adds a pet. */
    public void addPet(Pet pet) {
        pets.add(pet);
    }

    public Owner() {}
}
"""


def _check_ranges(text: str, spans) -> None:
    lines = text.split("\n")
    for span in spans:
        assert text[span.char_start : span.char_end] == span.text
        assert span.text == "\n".join(lines[span.line_start - 1 : span.line_end])


def test_java_spans_hold_a_class_header_with_its_members_and_their_javadoc() -> None:
    spans = derive_code_spans(JAVA, "java")

    # The preamble alone; the class header, its annotation, and every member in one span.
    assert [(s.line_start, s.line_end, s.section_path) for s in spans] == [(1, 3, ()), (5, 15, ("Owner",))]
    assert spans[1].text.startswith("/** An owner. */\n@Entity") and "/** Adds a pet. */" in spans[1].text
    _check_ranges(JAVA, spans)


def test_members_merge_up_to_the_bound_and_are_never_split() -> None:
    methods = "\n".join(
        f"    /** Step {i}. */\n    @GetMapping(\"/step/{i}\")\n    public int step{i}() {{\n        return {i};\n    }}\n"
        for i in range(1, 31)
    )
    text = f"package demo;\n\nclass Steps {{\n\n{methods}}}\n"

    spans = derive_code_spans(text, "java")

    assert len(spans) > 2 and spans[0].section_path == ()
    for span in spans[1:]:
        assert span.line_end - span.line_start + 1 <= MERGE_MAX_LINES and len(span.text) <= MAX_SPAN_CHARS
        # Every span starts at a member's Javadoc (or the class header) and ends with a closing brace.
        assert span.text.lstrip().startswith(("/** Step", "class Steps")) and span.text.rstrip().endswith("}")
    assert all(span.section_path == ("Steps",) or span.section_path[0] == "Steps" for span in spans[1:])
    _check_ranges(text, spans)


def test_python_spans_start_at_the_first_decorator() -> None:
    text = "import os\n\n\nclass A:\n    x = 1\n\n    @staticmethod\n    @cache\n    def f():\n        return os.sep\n"

    spans = derive_code_spans(text, "python")

    assert [(s.line_start, s.line_end, s.section_path) for s in spans] == [(1, 1, ()), (4, 10, ("A",))]
    assert spans[1].text.split("\n")[3].strip() == "@staticmethod"
    _check_ranges(text, spans)


def test_a_file_without_a_parser_is_windowed_with_overlap_and_bounded() -> None:
    text = "\n".join(f"key{i} = {'v' * 60}" for i in range(1, 151))

    spans = derive_code_spans(text, "properties")

    assert spans[0].line_start == 1 and spans[-1].line_end == 150
    for previous, current in zip(spans, spans[1:], strict=False):
        assert current.line_start <= previous.line_end + 1  # no line falls between two windows
        assert previous.line_end - current.line_start + 1 <= OVERLAP_LINES
    assert all(len(s.text) <= MAX_SPAN_CHARS and s.line_end - s.line_start < WINDOW_LINES for s in spans)
    _check_ranges(text, spans)


def test_redaction_keeps_every_line_where_it_was() -> None:
    text = (
        "url = https://deploy:hunter2@repo.example.com/x\n"
        "token = ghp_" + "a" * 36 + "\n"
        "-----BEGIN RSA PRIVATE KEY-----\nMIIEow\n-----END RSA PRIVATE KEY-----\n"
        "spring.datasource.password=petclinic\n"
    )

    redacted = redact_repository_text(text)

    assert redacted.text.count("\n") == text.count("\n")
    assert "hunter2" not in redacted.text and "ghp_" not in redacted.text and "MIIEow" not in redacted.text
    # A configuration key named password is a fact about the code, not a secret.
    assert redacted.text.splitlines()[5] == "spring.datasource.password=petclinic"
    assert redacted.redactions == 5


def test_line_links_and_path_rules() -> None:
    url = "https://github.com/o/r/blob/" + "a" * 40 + "/A.java"
    assert line_link(url, 3, 9) == f"{url}#L3-L9"
    assert line_link(url, 4, 4) == f"{url}#L4"
    assert line_link(f"{url}#top", 3, 9) == f"{url}#top"
    assert line_link(url, None, None) == url
    paths = PathFilter(("src/**/*.java", "pom.xml"), ("**/test/**",))
    assert paths.admits("src/A.java") and paths.admits("src/a/b/A.java") and paths.admits("pom.xml")
    assert not paths.admits("src/test/A.java") and not paths.admits("README.md")
    assert language_of("src/A.java") == "java" and language_of("Dockerfile") == "dockerfile"
    assert language_of("LICENSE") is None
