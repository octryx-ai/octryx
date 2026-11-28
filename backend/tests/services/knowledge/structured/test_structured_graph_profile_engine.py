"""Every profile pattern runs on the linear-time RE2 engine, with Python's semantics and a capped text."""

from __future__ import annotations

import copy
import json
import re
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from app.services.knowledge.structured.profile import default_profile_document, structured_profile
from app.services.knowledge.structured.profile_patterns import (
    MAX_MATCH_INPUT_CHARS,
    ProfilePattern,
    UnsupportedPatternError,
    check_pattern,
)
from app.services.knowledge.structured.profile_types import StructuredProfileError
from app.services.knowledge.structured.tickets import ticket_mentions
from app.services.knowledge.structured.workspace_profile import validate_document

BACKEND = Path(__file__).resolve().parents[4]
# Each passes the structural first line (no nested repeat), and each backtracks exponentially on ``re``.
PROBES = [r"(a|a)*c", r"(a|aa)*c", r"\d*\d*\d*\d*\d*\d*\d*\d*x"]


def test_the_backtracking_probes_finish_fast_in_a_workspace_profile():
    # In a child process with a deadline: on a backtracking engine the probes never return, and a hung
    # test would not fail; the child also runs them as Workspace ticket patterns through the extractor.
    script = textwrap.dedent(f"""
        import json, time
        from app.services.knowledge.structured.profile import default_profile_document
        from app.services.knowledge.structured.profile_patterns import check_pattern
        from app.services.knowledge.structured.tickets import ticket_mentions
        from app.services.knowledge.structured.workspace_profile import validate_document

        probes = {PROBES!r}
        texts = ["a" * 5000, "1" * 5000, "a" * 64, "1" * 64]
        started = time.monotonic()
        found = [check_pattern(p).search(t) is not None for p in probes for t in texts]
        document = default_profile_document()
        document["operations"]["ticket_patterns"] = {{f"Probe{{chr(65 + i)}}": p for i, p in enumerate(probes)}}
        profile = validate_document(document)
        mentions = [ticket_mentions(t, profile, None) for t in texts]
        print(json.dumps({{"found": found, "mentions": len(sum(mentions, [])),
                           "seconds": time.monotonic() - started}}))
    """)
    done = subprocess.run([sys.executable, "-c", script], cwd=BACKEND, capture_output=True, text=True, timeout=60)
    assert done.returncode == 0, done.stderr[-2000:]
    result = json.loads(done.stdout.strip().splitlines()[-1])
    assert result["found"] == [False] * 12 and result["mentions"] == 0
    assert result["seconds"] < 2.0


def test_every_profile_pattern_of_the_default_runs_on_re2():
    profile = structured_profile()
    patterns = [
        *profile.ignored_headings, *profile.filler_lines, *profile.allowed_value_patterns,
        *(item.pattern for item in profile.reference_patterns), *profile.variant_patterns,
        profile.placeholder_pattern, *profile.non_comparable_defaults, *(p for _, p in profile.ticket_patterns),
        *profile.caused_by_patterns, profile.inventory_namespace_pattern, profile.inventory_cluster_pattern,
    ]
    assert patterns and all(type(pattern) is ProfilePattern for pattern in patterns)
    assert not any(isinstance(pattern, re.Pattern) for pattern in patterns)


@pytest.mark.parametrize(("pattern", "text"), [
    (r"([A-Z][\w.\-]*(?: [A-Z][\w.\-]*){0,5}) \(page ([0-9]{1,4})\)", "see Café Menu (page 12)"),
    (r"^[^\w(]+\s", "ü Hinweis"),  # no match: ü is a word character (RE2's own \w is ASCII)
    (r"^[^\w(]+\s", "• Hinweis"),
    (r"^\w+(?: \w+){3,}", "Größe der Datei in Bytes"),
    (r"\d+", "Wert ٤٢ und 7"),
    (r"a\sb", "a\xa0b"),
    (r"\S+\Z", "Ende straße"),
    (r"\$\{(?P<name>[A-Za-z_][\w.-]{0,120})\}", "x=${Conf_Größe.max}"),
    (r"(?i)\bcaused by\s+(?:the\s+)?(?:change\s+)?(CHG[0-9]{7})\b", "Caused by the change CHG0001234."),
])
def test_unicode_classes_keep_python_semantics(pattern, text):
    expected = re.search(pattern, text)
    found = check_pattern(pattern).search(text)
    assert (found is None) == (expected is None)
    if expected is not None:
        assert found.span() == expected.span() and found.groups() == expected.groups()


@pytest.mark.parametrize("pattern", [r"(?=a)b", r"(?<=x)y", r"(a)\1", r"[^\W]", r"[\S]x", r"(?x) a b"])
def test_a_pattern_re2_cannot_run_is_refused_on_save(pattern):
    with pytest.raises(UnsupportedPatternError):
        check_pattern(pattern)
    document = copy.deepcopy(default_profile_document())
    document["manual"]["filler_lines"] = [pattern]
    with pytest.raises(StructuredProfileError, match="RE2"):
        validate_document(document)


def test_the_static_first_line_still_refuses_nested_repeats():
    document = copy.deepcopy(default_profile_document())
    document["manual"]["filler_lines"] = [r"(a+)+"]
    with pytest.raises(StructuredProfileError, match="backtrack"):
        validate_document(document)


def test_every_pattern_sees_at_most_the_capped_text():
    pattern = check_pattern(r"INC[0-9]{7}")
    head = "x" * (MAX_MATCH_INPUT_CHARS - 4)
    assert pattern.search(head + "INC0000001") is None  # straddles the cap
    assert pattern.search("INC0000001" + head) is not None
    assert [m.start() for m in pattern.finditer("INC0000001 " + head + "INC0000002")] == [0]
    assert pattern.fullmatch("INC0000001") is not None
    assert check_pattern(r"x+").fullmatch("x" * (MAX_MATCH_INPUT_CHARS + 1)) is None
    tail = "${b}"
    placeholder = check_pattern(r"\$\{(?P<name>\w+)\}")
    replaced = placeholder.sub(lambda m: m.group("name").upper(), "${a}" + head + tail)
    assert replaced.startswith("A") and replaced.endswith(tail)
    long_record = "INC0000001 " + "y" * MAX_MATCH_INPUT_CHARS + " INC0000002"
    assert [number for _, number, _ in ticket_mentions(long_record, structured_profile(), None)] == ["INC0000001"]


def test_matches_answer_by_group_name_like_re():
    found = structured_profile().inventory_cluster_pattern.search("x\nCluster: EKS prod-1\n")
    assert found.group("cluster") == "prod-1" and found.start("cluster") == found.start(1) == 15
    assert found.end("cluster") == 21 and found.span("cluster") == (15, 21) and found["cluster"] == "prod-1"
    assert found.groupdict() == {"cluster": "prod-1"}
