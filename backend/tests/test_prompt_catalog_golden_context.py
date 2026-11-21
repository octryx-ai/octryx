"""Golden scenarios of the context prompts: the seed renders the pinned digests.

The digests pin the inputs of ``tests/prompt_catalog_golden_context_support.py`` (summarizer, injected summary,
evidence references, compaction, checkpoint, agent execution prompt, personality lines). A deliberate change to a
seeded context prompt re-pins the affected digests.
"""

from __future__ import annotations

from hashlib import sha256

from tests.prompt_catalog_golden_context_support import context_outputs

PINNED_DIGESTS = {
    "agent:bare": "85cfc2b547435be16f7df718a80af1f40f2065fba559df0696df9e6579bf0c8b",
    "agent:full": "43d01733099bcaa8695484201de14fb67d62903fddf3f0b8d002c80f91ff7d22",
    "checkpoint": "f1a04db9855d6d0a4c62a687a9a6353d0b38641760cbabee73f569782af09cf7",
    "compaction": "880202612494e858d6e8f2779aeafa8095dc51d037228e43cc16e2c8c5e660c9",
    "compaction:bare": "ea26962597a77e3a20aa7afcd9b691ad5b1fb7683117880f69d1697da059a18f",
    "evidence_block": "8864f1572f6908468b629c0fbcfbbab8fb787b81d72114a760c1b692a0f8ba28",
    "evidence_block:empty": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
    "history:json:refs": "9e326ad61272f423e8c8874fe9a4ca3897106d33d8cb8550d983aacdf8800268",
    "history:text": "6c1da8ecc9de2565d0ff1b6283596ad8f3fa6b2fc55e3cd66d1688618aed72b9",
    "personality:0": "9defd878674d8a7b11232081183ffa7c542cac48591d886c810a9dcf3b167d57",
    "personality:1": "34ca8dddfba22e8148404b93e6064514912b2d7835aa12e791fb2cc731fdba96",
    "personality:2": "79ceec9707b616e7da8b1db2804bf691a25a45fce350edc413c743b42adbadfd",
    "personality:3": "42683d02aea942313b2d5657f8573ee30dfee131e79a3b192a7d4d67881e14f5",
    "personality:4": "94096fe9e29126086cdce59a8c64e1571844784903bdb0c02975fb134bef61a4",
    "summarizer:system": "116b4254c74e867359fcc3fdb4e1d3e2e81247d225c72061c2ecf6ba4c4ff77b",
    "summarizer:user": "375784f602ddac77ad7a390808edd5e61ec6eb61181802286ca2778dc1f175f1",
    "summarizer:user:first": "db623b8e46f76013566827b3f1d1bbfa648d671e9d29e53d9fde00d218cf0a17",
}


def test_the_context_prompts_render_byte_identical_from_the_seed() -> None:
    outputs = context_outputs()
    assert {name: sha256(text.encode()).hexdigest() for name, text in outputs.items()} == PINNED_DIGESTS
