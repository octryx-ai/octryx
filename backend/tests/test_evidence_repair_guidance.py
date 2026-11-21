"""The single reminder identifies missing citations without accepting them."""

from app.services.answer_evidence.check import check_answer_evidence, evidence_reminder
from app.services.answer_evidence.evidence import EvidenceSource, TurnEvidence


def test_reminder_identifies_only_uncited_blocks_and_keeps_fail_closed_policy():
    evidence = TurnEvidence(linkable=(EvidenceSource("https://example.com/a", "[source](https://example.com/a)"),),
                            result_urls=frozenset({"https://example.com/a"}))
    missing = "- The submitted entity uses the validator registered by its controller."
    check = check_answer_evidence(
        # Two claims (list items): an opening paragraph would frame the answer and not count.
        "- The controller handles the endpoint [source](https://example.com/a).\n" + missing, evidence,
    )
    assert check.cited_count == 1
    assert check.uncited_count == 1
    assert check.uncited_blocks == (missing,)
    assert not check.satisfied
    reminder = evidence_reminder(check)
    assert '"uncited_blocks"' in reminder
    assert missing in reminder
    assert "untrusted draft data" in reminder


def test_uncited_repair_data_is_bounded():
    evidence = TurnEvidence(linkable=(EvidenceSource("https://example.com/a", "[source](https://example.com/a)"),))
    check = check_answer_evidence("\n\n".join("word " * 200 for _ in range(20)), evidence)
    assert check.uncited_count == 20
    assert len(check.uncited_blocks) == 16
    assert all(len(block) <= 400 for block in check.uncited_blocks)
    assert not check.satisfied


def test_all_eleven_uncited_blocks_are_identified_for_repair():
    evidence = TurnEvidence(linkable=(EvidenceSource("https://example.com/a", "[source](https://example.com/a)"),))
    blocks = [f"- The validated record number {index} is checked before it is stored." for index in range(11)]
    check = check_answer_evidence("\n".join(blocks), evidence)
    assert check.uncited_count == 11
    assert check.uncited_blocks == tuple(blocks)
