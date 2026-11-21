"""Spec Studio: the product owner sees, decides and approves the spec instead of reading markdown.

In a benchmark, 30 of 44 findings were spec gaps, while the engines' implementation gaps
were 0 (Claude) and 4 (Codex). A markdown spec and an interview card are not good enough for a product owner,
above all for design. The spec-writing draft phase therefore records a structured artefact next to SPEC.md (phase
output ``spec_studio``):

- ``schema``: the artefact — design directions with tokens, screens as mock blocks with data and empty states,
  questions with one proposal, rules with worked examples, acceptance criteria, requirements with zero-config,
  glossary and condition words; ``mode: feature`` carries only the delta of a feature on an approved app;
- ``gates``: the spec checks and WCAG AA; every miss is an open point that blocks approval;
- ``state``: the product owner's answers, token choices, pinned comments, rule values and criterion verdicts, each
  change one audited run event;
- ``freeze``: approval freezes artefact + state as version n (the review baseline, hands_on scenarios), writes the
  decisions back into SPEC.md (``writeback``) and confirms the spec's decisions gate; revision sends one composed
  answer back to the draft phase.
"""
