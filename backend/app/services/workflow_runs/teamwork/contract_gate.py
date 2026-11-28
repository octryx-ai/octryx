"""The story contract is complete before any item starts (a missing section otherwise costs a whole re-plan)."""

from __future__ import annotations

import re
from typing import Any

CHECK_TYPE = "story_contract_complete"
_NUMBER = r"\d+(?:\.\d+)*[a-z]?"
_LIST = rf"§?\s*{_NUMBER}(?:\s*(?:,|/|&|and)\s*§?\s*{_NUMBER})*"
# "contract 2.1", "contract section 2.1", "contract sections 2.1, 2.2", ".md 3.1", "the contract's 2.4"
_AFTER = re.compile(rf"(?:\bcontract(?:'s)?|docs/stories/[\w.-]+\.md|\b[A-Z][A-Z0-9]*-\d+\.md)\s*(?:,\s*)?"
                    rf"(?:\(?\s*(?:sections?|§)\s*)?({_LIST})", re.IGNORECASE)
# "sections 3.1, 3.3 and 5 of docs/stories/.md", "section 2.4 of the contract"
_BEFORE = re.compile(rf"\bsections?\s+({_LIST})\s+(?:of|in)\s+(?:the\s+)?(?:story\s+)?"
                     r"(?:contract|docs/stories/[\w.-]+\.md|[A-Z][A-Z0-9]*-\d+\.md)", re.IGNORECASE)
_SECTION_SIGN = re.compile(rf"§\s*({_NUMBER})")
_ONE = re.compile(_NUMBER)
_HEADING = re.compile(rf"^[\s#>*_|`-]*(?:§\s*|section\s+)?({_NUMBER})(?=[\s.):,*_|`-]|$)", re.IGNORECASE | re.MULTILINE)


def cited_sections(text: str) -> list[str]:
    found: list[str] = []
    for pattern in (_AFTER, _BEFORE, _SECTION_SIGN):
        for match in pattern.finditer(text or ""):
            for number in _ONE.findall(match.group(1)):
                if number not in found:
                    found.append(number)
    return found


def contract_sections(text: str) -> set[str]:
    numbers: set[str] = set()
    for match in _HEADING.finditer(text or ""):
        number = match.group(1).lower()
        numbers.add(number)
        parts = re.sub(r"[a-z]$", "", number).split(".")
        numbers.update(".".join(parts[:end]) for end in range(1, len(parts)))
    return numbers


def new_story_contracts(change: Any) -> str | None:
    # Only new files: their whole text is in the patch.
    if not isinstance(change, dict) or change.get("truncated") or change.get("base_unavailable"):
        return None
    patch = change.get("patch")
    if not isinstance(patch, str) or not patch:
        return None
    texts: list[str] = []
    for block in re.split(r"^(?=diff --git )", patch, flags=re.MULTILINE):
        header = re.match(r"diff --git a/(\S+) b/(\S+)", block)
        if not header or not re.fullmatch(r"docs/stories/[^/]+\.md", header.group(2)):
            continue
        if "\nnew file mode" not in block.split("@@", 1)[0]:
            return None  # an existing contract changed: only its changed lines are here, nothing can be judged
        texts.append("\n".join(line[1:] for line in block.splitlines()
                               if line.startswith("+") and not line.startswith("+++")))
    return "\n".join(texts) if texts else None


def missing_sections(record: dict[str, Any], contract_text: str) -> dict[str, list[str]]:
    present = contract_sections(contract_text)
    missing: dict[str, list[str]] = {}
    for item in record.get("items") or []:
        for number in cited_sections(str(item.get("instructions") or "")):
            if number.lower() not in present:
                missing.setdefault(number, []).append(str(item.get("id") or "?"))
    return missing


def contract_gap_result(run: Any, change: Any) -> Any:
    from ...workflow_checks.library import FAILED, CheckResult
    from ..phase_outputs import recorded_output
    from . import OUTPUT_KIND

    record = dict(dict(recorded_output(run, OUTPUT_KIND) or {}).get("record") or {})
    written = new_story_contracts(change)
    if not record.get("items") or written is None:
        return None
    missing = missing_sections(record, f"{written}\n{record.get('contract') or ''}")
    if not missing:
        return None
    cited = "; ".join(f"{number} (cited by {', '.join(items)})" for number, items in missing.items())
    return CheckResult(type=CHECK_TYPE, outcome=FAILED, blocking=True, detail="", description=(
        f"Story contract: your items cite sections the contract file does not have: {cited}. Write each of them "
        "into docs/stories/<KEY>.md now (or correct the item's reference and submit the plan again), so no item "
        "blocks on a missing section later."))


__all__ = ["CHECK_TYPE", "cited_sections", "contract_gap_result", "contract_sections", "missing_sections",
           "new_story_contracts"]
