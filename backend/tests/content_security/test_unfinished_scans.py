"""Every scan that decides what is sent or released treats an unfinished scan explicitly (fail closed).

``ScanReport.unfinished`` (readable text not fully examined: size or time budget, candidate limit) is told apart
from unreadable media; each consumer gives it a disposition instead of reading "no finding" as clean:

- masking (``body_masking.MaskRun``: Workspace mask obligations in governed chat and tool results)
  withholds the text;
- every content decision refuses it (``content_scan_unfinished``), whatever the built-in check or Cedar says;
- a tool result deeper than the scan reads is withheld from the masked result and marks the scan incomplete;
- command safety sends the command for review;
- a platform chat message part of an unknown shape is scanned as its JSON text, never skipped (the gateway reads
  every body as its JSON text).
"""

from __future__ import annotations

import asyncio

from app.services.content_detection.examination import RequestBudget, examine, examine_text
from app.services.content_detection.masking import WITHHELD_TEXT
from app.services.content_detection.scanner import DetectorSet, Segment
from app.services.content_detection.vocabulary import SOURCE_PROMPT
from app.services.content_routing.body_masking import MaskRun, mask_chat_messages
from app.services.content_routing.decision import REASON_SCAN_UNFINISHED
from app.services.content_routing.gateway import fixed_refusal, scan_request
from app.services.content_routing.gateway_outcome import GatewayOutcome
from app.services.content_routing.segments import chat_segments
from app.services.content_routing.tool_results import MAX_DEPTH, _masked, _segments
from app.services.security_analyzer.content_command import content_command_analyzer

EMAIL = "jane.doe@example.org"
# More candidates than a detector examines in one text: the scan of this text cannot finish.
UNFINISHED = " ".join(f"10.2.{index // 250}.{index % 250}" for index in range(5200))
EMAILS = " ".join(f"user{index}@example.org" for index in range(5200))


def test_an_unfinished_text_is_told_apart_from_unreadable_media():
    unfinished = examine_text(UNFINISHED, SOURCE_PROMPT, DetectorSet())
    media = examine([Segment("", SOURCE_PROMPT, readable=False)], DetectorSet())

    assert not unfinished.finished and not unfinished.report.complete
    assert media.finished and not media.report.complete
    assert unfinished.report.summary()["unfinished"] is True


def test_masking_withholds_a_text_it_cannot_finish():
    detectors = DetectorSet(builtin=frozenset({"email"}))
    run = MaskRun(detectors, frozenset({"email"}), None)

    assert run.text(EMAILS) == WITHHELD_TEXT and run.withheld == 1
    assert run.text(f"Mail {EMAIL}.") == "Mail [EMAIL #1]."
    masked = mask_chat_messages([{"role": "user", "content": EMAILS}], detectors, frozenset({"email"}), None)
    assert masked.body == [{"role": "user", "content": WITHHELD_TEXT}] and masked.withheld == 1


def test_the_gateway_decision_refuses_an_unfinished_scan_and_passes_media():
    assignments = " ".join(f"password=Value{index}x" for index in range(5200))  # a gateway kind, past its limit
    unfinished = scan_request({"messages": [{"role": "user", "content": assignments}]}, "ws-1", RequestBudget())
    media = scan_request({"messages": [{"role": "user", "content": [
        {"type": "image", "source": {"type": "base64", "data": "AAAA"}}]}]}, "ws-1", RequestBudget())

    assert not unfinished.finished and media.finished
    assert fixed_refusal(media, GatewayOutcome(), media.finished) is None
    refused = fixed_refusal(unfinished, GatewayOutcome(), unfinished.finished)
    assert (refused.reason, refused.http_status) == (REASON_SCAN_UNFINISHED, 400)


def _nested(depth: int, leaf: str) -> object:
    value: object = leaf
    for _ in range(depth):
        value = {"inner": value}
    return value


def test_a_tool_result_deeper_than_the_scan_reads_is_withheld_and_marks_the_scan_incomplete():
    deep = _nested(MAX_DEPTH + 3, f"mail {EMAIL}")

    assert any(not segment.readable for segment in _segments(deep))
    assert EMAIL not in str(_masked(deep, lambda text: text)) and WITHHELD_TEXT in str(_masked(deep, str))


def test_command_safety_reviews_a_command_it_cannot_finish_scanning():
    finding = asyncio.run(content_command_analyzer("run_cli_command", f"ping {UNFINISHED}", None))

    assert finding.action == "review" and finding.details["unfinished"] is True


def test_a_message_part_of_an_unknown_shape_is_scanned_as_its_text():
    chat = chat_segments([{"role": "user", "content": {"unexpected": EMAIL}}])

    assert any(EMAIL in segment.text for segment in chat)
