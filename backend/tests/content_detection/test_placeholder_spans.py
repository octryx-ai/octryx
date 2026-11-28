from __future__ import annotations

import pytest

from app.services.content_detection import examination
from app.services.content_detection.custom_validation import check_detector_set
from app.services.content_detection.examination import RequestBudget, examine_text
from app.services.content_detection.findings import Finding
from app.services.content_detection.masking import Masker, PlaceholderSpans, mask_text
from app.services.content_detection.registry import detector_set_for
from app.services.content_detection.scanner import Segment
from app.services.content_routing.decision import scan_for
from app.services.content_security.transport import TransportRun, mask_run
from app.services.policy_engine.runtime import PolicyRuntime


def _definitions(*detectors: tuple[str, str]):
    return check_detector_set({"detectors": [{"id": detector_id, "label": "Reference", "category": "secrets",
                                              "pattern": pattern} for detector_id, pattern in detectors]})


def _masked(text: str, definitions, mask: set[str], style: str | None = None) -> tuple[str, TransportRun]:
    run = mask_run(detector_set_for(definitions, "ws-1"), frozenset(mask), style)
    return run.text(text), run


def _detected(text: str, definitions, placeholders: PlaceholderSpans | None) -> dict[str, int]:
    runtime = PolicyRuntime(custom_detectors=definitions)
    budget = RequestBudget() if placeholders is not None else None
    scans = scan_for([Segment(text, "tool_result")], "ws-1", runtime, budget=budget, placeholders=placeholders)
    return scans.live.report.counts()


def _finding(start: int, end: int) -> Finding:
    return Finding("custom.acme", "secrets", "medium", start, end)


def test_spans_cover_only_generated_characters_at_their_offsets_in_the_masked_text():
    detectors = detector_set_for(_definitions(("custom.acme", r"ACME-[0-9]+")), "ws-1")
    text = "a ACME-1 bb jane.doe@example.org ccc +49 30 1234567 d ACME-22"
    result = mask_text(text, examine_text(text, "tool_result", detectors).findings[0], detectors=detectors,
                       mask=frozenset({"custom.acme", "email", "phone"}), style="last4", masker=Masker())
    masked = result.text
    assert masked == "a [ACME *CME1 #1] bb [EMAIL #2] ccc [PHONE *******4567 #3] d [ACME **ME22 #4]"
    assert [masked[start:end] for start, end in result.generated] == [
        "[ACME *", " #1]", "[EMAIL #2]", "[PHONE *******", " #3]", "[ACME **", " #4]"]


def test_country_last4_retains_the_country_and_the_last_four():
    detectors = detector_set_for(_definitions(), "ws-1")
    text = "iban DE89370400440532013000"
    result = mask_text(text, examine_text(text, "tool_result", detectors).findings[0], detectors=detectors,
                       mask=frozenset({"iban"}), style="country_last4", masker=Masker())
    assert result.text == "iban [IBAN DE…3000]"
    assert [result.text[start:end] for start, end in result.generated] == ["[IBAN ", "…", "]"]


def test_a_finding_inside_a_span_only_of_the_same_text_object_is_covered():
    definitions = _definitions(("custom.acme", r"ACME-[0-9]+"))
    masked, run = _masked("ref ACME-1 end", definitions, {"custom.acme"})
    assert masked == "ref [ACME #1] end"
    assert run.placeholders.covers(masked, _finding(5, 12))
    assert run.placeholders.covers(masked, _finding(4, 13))
    assert not run.placeholders.covers(masked, _finding(3, 8)), "overlaps the start"
    assert not run.placeholders.covers(masked, _finding(10, 15)), "overlaps the end"
    assert not run.placeholders.covers(masked, _finding(14, 17)), "outside"
    assert not run.placeholders.covers("".join(list(masked)), _finding(5, 12)), "equal text, another object"


def test_the_rescan_drops_only_findings_inside_a_placeholder():
    definitions = _definitions(("custom.acme", r"ACME[- #0-9]*"), ("custom.tail", r"\]tail"))
    masked, run = _masked("ACME-1tail and ACME-2", definitions, {"custom.acme"})
    assert masked == "[ACME #1]tail and [ACME #2]"
    assert _detected(masked, definitions, None) == {"custom.acme": 2, "custom.tail": 1}
    assert _detected(masked, definitions, run.placeholders) == {"custom.tail": 1}, "the boundary overlap counts"


def test_sensitive_text_next_to_a_placeholder_is_still_found():
    definitions = _definitions(("custom.acme", r"ACME[- #0-9]*"))
    masked, run = _masked("ACME-1jane.doe@example.org ACME-2", definitions, {"custom.acme"})
    assert masked == "[ACME #1]jane.doe@example.org [ACME #2]"
    assert _detected(masked, definitions, run.placeholders) == {"email": 1}


def test_a_value_outside_every_span_still_counts():
    definitions = _definitions(("custom.acme", r"ACME-[0-9]+"))
    masked, run = _masked("ACME-1 mail jane.doe@example.org", definitions, {"email"})
    assert masked == "ACME-1 mail [EMAIL #1]"
    assert _detected(masked, definitions, run.placeholders) == {"custom.acme": 1}


def test_a_retained_last4_that_another_detector_matches_is_still_found():
    definitions = _definitions(("custom.acme", r"ACME-[0-9]+"), ("custom.tail", r"0042"))
    masked, run = _masked("ref ACME-120042 open", definitions, {"custom.acme"}, "last4")
    assert masked == "ref [ACME **0042 #1] open"
    assert _detected(masked, definitions, run.placeholders) == {"custom.tail": 1}


def test_a_retained_alphanumeric_fallback_that_another_detector_matches_is_still_found():
    definitions = _definitions(("custom.ref", r"REF-[A-Z]+"), ("custom.word", r"DEFG"))
    masked, run = _masked("ref REF-ABCDEFG open", definitions, {"custom.ref"}, "last4")
    assert masked == "ref [REF ******DEFG #1] open"
    assert _detected(masked, definitions, run.placeholders) == {"custom.word": 1}


def test_a_self_matching_detector_on_its_retained_last4_still_counts():
    definitions = _definitions(("custom.zx", r"ZX-[0-9]{6}|0042"))
    masked, run = _masked("ref ZX-120042 open", definitions, {"custom.zx"}, "last4")
    assert masked == "ref [ZX **0042 #1] open"
    assert _detected(masked, definitions, run.placeholders) == {"custom.zx": 1}


def test_many_placeholders_and_findings_are_filtered_exactly():
    definitions = _definitions(("custom.acme", r"ACME[- #0-9]*"), ("custom.seam", r"\]\["))
    count = 400
    text = " ".join(f"ACME-{index}" for index in range(count)) + " mail jane.doe@example.org"
    masked, run = _masked(text, definitions, {"custom.acme"})
    assert masked.count("[ACME #") == count
    assert _detected(masked, definitions, None)["custom.acme"] == count
    assert _detected(masked, definitions, run.placeholders) == {"custom.seam": count - 1, "email": 1}


def _counting_covers(monkeypatch, after=None) -> list[int]:
    calls: list[int] = []
    real = PlaceholderSpans.covers

    def counted(self, text, finding):
        calls.append(1)
        if after is not None and len(calls) == after[0]:
            after[1].deadline = 0.0
        return real(self, text, finding)

    monkeypatch.setattr(PlaceholderSpans, "covers", counted)
    return calls


def _rescan(masked: str, definitions, run: TransportRun, budget: RequestBudget):
    return scan_for([Segment(masked, "tool_result")], "ws-1", PolicyRuntime(custom_detectors=definitions),
                    budget=budget, placeholders=run.placeholders)


def test_a_deadline_expiring_during_the_filter_stops_it_and_leaves_the_rescan_unfinished(monkeypatch):
    definitions = _definitions(("custom.acme", r"ACME[- #0-9]*"))
    masked, run = _masked(" ".join(f"ACME-{index}" for index in range(10)), definitions, {"custom.acme"})
    budget = RequestBudget()
    calls = _counting_covers(monkeypatch, after=(3, budget))
    scans = _rescan(masked, definitions, run, budget)
    assert not scans.live.finished and scans.live.report.counts() == {}
    assert len(calls) == 3


def test_a_deadline_expired_by_the_scan_skips_the_filter(monkeypatch):
    definitions = _definitions(("custom.acme", r"ACME[- #0-9]*"))
    masked, run = _masked("ref ACME-1", definitions, {"custom.acme"})
    budget = RequestBudget()
    calls = _counting_covers(monkeypatch)
    real_scan = examination.scan

    def expiring(*args):
        report = real_scan(*args)
        budget.deadline = 0.0
        return report

    monkeypatch.setattr(examination, "scan", expiring)
    scans = _rescan(masked, definitions, run, budget)
    assert not scans.live.finished and calls == []


def test_a_placeholder_filter_without_a_budget_is_refused():
    definitions = _definitions(("custom.acme", r"ACME[- #0-9]*"))
    masked, run = _masked("ref ACME-1", definitions, {"custom.acme"})
    with pytest.raises(ValueError, match="request budget"):
        scan_for([Segment(masked, "tool_result")], "ws-1", PolicyRuntime(custom_detectors=definitions),
                 placeholders=run.placeholders)


def test_the_tool_result_rescan_keeps_the_enforcement_deadline(monkeypatch):
    from app.services.content_routing import decision, tool_results

    created: list[tuple[dict, RequestBudget]] = []
    passed: list[RequestBudget | None] = []

    class Recorded(RequestBudget):
        def __init__(self, **kwargs) -> None:
            super().__init__(**kwargs)
            created.append((kwargs, self))

    def recorded_scan(segments, workspace_id, runtime=None, budget=None, placeholders=None):
        passed.append(budget)
        return "scans"

    monkeypatch.setattr(decision, "RequestBudget", Recorded)
    monkeypatch.setattr(tool_results, "scan_for", recorded_scan)
    monkeypatch.setattr(tool_results, "decide_tool_result", lambda **kwargs: kwargs["scans"])
    run = mask_run(detector_set_for(_definitions(), "ws-1"), frozenset({"email"}), None)
    masked = {"text": run.text("mail jane.doe@example.org")}
    assert tool_results._decide(masked, {"workspace_id": "ws-1"}, frozenset(), run.placeholders) == "scans"
    [(kwargs, budget)] = created
    assert kwargs == {"max_chars": 16_000_000, "deadline_ms": 2000.0}
    assert passed == [budget]
    assert tool_results._decide(masked, {"workspace_id": "ws-1"}, frozenset()) == "scans"
    assert passed[-1] is None and len(created) == 1, "the first decision keeps the scanner's own budget"


def test_a_zero_width_alternative_neither_crashes_nor_drops_a_real_value():
    definitions = _definitions(("custom.zx", r"ZX-[0-9]{4}|\b"))
    masked, run = _masked("ref ZX-1234 open", definitions, {"custom.zx"})
    assert masked == "ref [ZX #1] open"
    assert _detected(masked, definitions, run.placeholders) == {}
    kept, other = _masked("ZX-1234 mail jane.doe@example.org", definitions, {"email"})
    assert _detected(kept, definitions, other.placeholders) == {"custom.zx": 1}
