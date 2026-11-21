"""The Memory lobe of the Knowledge module.

Knowledge is source-grounded and re-derivable; memory is experience from sessions and may be wrong.
The two lobes share the module facade and the Workspace authorization but nothing else: memory has
its own ledger (``models/project/knowledge_memory.py``), its own tools (``memory_remember``,
``memory_recall``), its own lifecycle (capture, consolidation, supersession, expiry, correction,
forgetting) and is never rendered as a cited source.

- ``capture``: explicit "remember this" as ``human_stated``;
- ``recall``: bounded lexical recall, visibility-filtered;
- ``control``: list, confirm, correct, forget;
- ``visibility``: personal vs Workspace items, and who may change them;
- ``presentation``: the ``kind: memory`` / ``not_source_evidence`` rendering;
- ``text_guard``: bounds, character safety and the secret refusal.
"""
