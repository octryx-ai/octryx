"""Custom detectors and categories: validation, scope, checks, context words, digest."""

from __future__ import annotations

import pytest

from app.services.content_detection.custom import compile_detector
from app.services.content_detection.custom_definitions import MAX_DETECTORS, DetectorSetError
from app.services.content_detection.custom_validation import check_detector_set
from app.services.content_detection.masking import Masker, mask_text
from app.services.content_detection.registry import detector_set_for
from app.services.content_detection.scanner import scan_text

from .vectors import MOD10_INVALID, MOD10_VALID

PATTERN = r"\bQX-\d{4}-\d{6}\b"


def _definition(**overrides):
    return {"id": "custom.case_ref", "label": "Case reference", "category": "confidential_identifier",
            "pattern": PATTERN, **overrides}


def _issues(raw):
    with pytest.raises(DetectorSetError) as caught:
        check_detector_set(raw)
    return [item["code"] for item in caught.value.issues]


def test_empty_definitions():
    assert check_detector_set(None).empty and check_detector_set({}).empty


def test_valid_definition_normalized_and_sorted():
    checked = check_detector_set({"categories": [{"id": "contracts", "label": "Contracts"}], "detectors": [
        _definition(id="custom.zeta", category="contracts", context_words=["Ref", "ref", "case"]),
        _definition(id="custom.alpha", mask_style="last4", workspace_id="ws-1"),
    ]})
    assert [item.id for item in checked.detectors] == ["custom.alpha", "custom.zeta"]
    zeta = checked.detectors[1]
    assert zeta.context_words == ("ref", "case") and zeta.confidence == "high"
    assert checked.detectors[0].confidence == "medium" and checked.detectors[0].workspace_id == "ws-1"
    assert checked.to_json()["detectors"][1]["context_words"] == ["ref", "case"]


@pytest.mark.parametrize(("override", "code"), [
    ({"id": "case_ref"}, "detector_id_invalid"),
    ({"id": "custom.Case"}, "detector_id_invalid"),
    ({"label": ""}, "detector_label_invalid"),
    ({"category": "nope"}, "detector_category_unknown"),
    ({"pattern": "x" * 301}, "pattern_too_long"),
    ({"pattern": "(a+)+b"}, "pattern_unsafe"),
    ({"pattern": r"(?<=a)b"}, "pattern_not_re2"),
    ({"pattern": "(ab"}, "pattern_syntax"),
    ({"pattern": "a*"}, "pattern_matches_empty"),
    ({"check": "sha1"}, "detector_check_invalid"),
    ({"context_words": ["x" * 41]}, "context_words_invalid"),
    ({"context_words": ["a"] * 11}, "context_words_invalid"),
    ({"context_words": "ref"}, "context_words_invalid"),
    ({"mask_style": "country_last4"}, "mask_style_invalid"),
    ({"workspace_id": 7}, "workspace_scope_invalid"),
    ({"sample": "QX-2026-000001"}, "detector_set_shape"),
])
def test_invalid_definitions_are_refused_with_an_issue(override, code):
    assert code in _issues({"detectors": [_definition(**override)]})


def test_duplicate_ids_too_many_and_bad_categories():
    assert "detector_id_duplicate" in _issues({"detectors": [_definition(), _definition()]})
    assert "detector_set_too_many" in _issues({"detectors": [_definition(id=f"custom.d{i:02d}")
                                                             for i in range(MAX_DETECTORS + 1)]})
    assert "category_id_invalid" in _issues({"categories": [{"id": "pii", "label": "People"}]})
    assert "detector_label_invalid" in _issues({"categories": [{"id": "contracts", "label": ""}]})
    assert "detector_set_shape" in _issues({"detectors": [], "samples": []})


def test_matches_with_context_words_and_checks():
    worded = compile_detector(check_detector_set({"detectors": [_definition(context_words=["case"])]}).detectors[0])
    assert [item.confidence for item in worded.find("case id QX-2026-000042 open")] == ["high"]
    assert worded.find("build QX-2026-000042 failed") == []
    assert worded.find("case " + "x" * 40 + " QX-2026-000042") == []  # the word is outside the ±32 window
    mod10 = compile_detector(check_detector_set({"detectors": [_definition(
        pattern=r"\b\d{11}\b", check="mod10")]}).detectors[0])
    assert len(mod10.find(f"a {MOD10_VALID} b {MOD10_INVALID}")) == 1
    mod97 = compile_detector(check_detector_set({"detectors": [_definition(
        pattern=r"\b[A-Z]{2}\d{20}\b", check="mod97")]}).detectors[0])
    assert len(mod97.find("DE89370400440532013000 DE89370400440532013001")) == 1


def test_the_mod10_check_keeps_only_the_valid_number():
    checked = check_detector_set({"detectors": [_definition(pattern=r"\b\d{11}\b", check="mod10")]})
    detector = compile_detector(checked.detectors[0])
    text = f"a {MOD10_VALID} b {MOD10_INVALID}"
    assert [text[item.start:item.end] for item in detector.find(text)] == [MOD10_VALID]


def test_workspace_scope_and_masking():
    definitions = check_detector_set({"detectors": [_definition(workspace_id="ws-1", mask_style="last4")]})
    in_scope = detector_set_for(definitions, "ws-1")
    assert scan_text("ref QX-2026-000042", "prompt", in_scope).detected == {"custom.case_ref"}
    assert scan_text("ref QX-2026-000042", "prompt", detector_set_for(definitions, "ws-2")).detected == frozenset()
    report = scan_text("ref QX-2026-000042", "prompt", in_scope)
    masked = mask_text("ref QX-2026-000042", report.findings[0], detectors=in_scope,
                       mask=frozenset({"custom.case_ref"}), style=None, masker=Masker())
    assert masked.text == "ref [CASE_REF ******0042 #1]"


def test_digest_changes_with_any_field():
    base = check_detector_set({"detectors": [_definition()]})
    other = check_detector_set({"detectors": [_definition(context_words=["case"])]})
    assert base.digest() != other.digest() and base.digest() == check_detector_set(
        {"detectors": [_definition()]}).digest()
