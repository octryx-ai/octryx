"""The reviewer's verdict: a closed schema, parsed strictly."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

VERDICT_PASS, VERDICT_CHANGES = "pass", "changes"
SEVERITIES = ("high", "medium", "low")
BLOCKING_SEVERITIES = frozenset({"high", "medium"})
ANSWER_CONTRACT = (
    'Answer with one JSON object only: {"verdict": "pass" or "changes", "summary": "<one sentence>", '
    '"findings": [{"severity": "high" or "medium" or "low", "file": "<path>", "line": <line number>, '
    '"fix": "<the concrete change the author must make>"}]}. "pass" may only carry low findings; '
    '"changes" names at least one finding. One finding is one problem: two problems are two findings, so each is '
    'answered and closed on its own.'
)

# The severities say what blocks: high breaks the work, medium is a visible defect the spec asks to avoid, low is
# polish; a spec review keeps its own scale.
SEVERITY_RULE = (
    'Severity: "high" only when the change breaks an acceptance criterion or a confirmed decision (a product owner '
    'answer, a decision of the specification), opens a security or data risk, or leaves a user unable to complete a '
    'task the work item names; "medium" for a visible defect or a missing state (empty, error, loading) the '
    'specification asks for; "low" for polish: spacing, wording, naming, style, a rewrite with the same behaviour, '
    'reusing another helper. Do not recompute values the tests compute (contrast ratios, sums, totals, '
    'percentages): a numeric disagreement is "low" unless a test proves it wrong.'
)

# A gap the spec did not state is decided silently by the agent; ``assumptions: true`` lists them for the person.
ASSUMPTIONS_RULE = (
    'Also add "assumptions": a list of short sentences, one for every behaviour the change decides that the work '
    'item and the specification do not state (a default value, a threshold, an edge case, a missing input, a '
    'contradiction resolved one way). Phrase each as a question the product owner can answer, naming what the '
    'change does now, for example "An item not in the inventory gets bonus 5: is that intended?". An empty list '
    'when the change decides nothing the spec leaves open.'
)

# Every review of a run with product owner answers checks them point by point.
PO_ANSWERS_RULE = (
    "The product owner's answers in the task are decisions the change must carry out; a later answer overrides an "
    "earlier one where they differ. Check every numbered or lettered point of every answer against the change: a "
    'point the change does not carry out, or carries out differently, is a finding of severity "high" whose fix '
    'starts with the point, for example "PO answer 2, point C: the plan test still has no inventory; ...". A point '
    "that asks for nothing to change, or that the code already met before this change, is not a finding."
)

# Accepted interview proposals can otherwise go missing from the specs unnoticed.
SPEC_DECISIONS_RULE = (
    "Every product owner answer in the task, including each proposal the product owner accepted, must appear in the "
    "specification's Decisions section (or be carried out where the specification states that topic). An answer or "
    'accepted proposal that is missing there, or that the specification contradicts, is a finding of severity "high" '
    'whose fix starts with the answer, for example "PO answer 1, item 4 (minimum stock): missing from Decisions; ...".'
)
# The bug flow: a fix must remove the cause, not hide the symptom.
ROOT_CAUSE_RULE = (
    "This change fixes a reported bug. Find its root cause in the code and start the summary with 'Root cause: "
    "<file>:<line> - <what is wrong there>'. Then say whether the change removes that cause. A change that only "
    "hides the symptom is a finding of severity \"high\" on the changed line, naming the cause it leaves in place: "
    "catching or swallowing the error, a guard that returns early or a default that masks wrong data, hiding or "
    "disabling the UI element, a retry or delay around the failure, a test changed to expect the wrong behaviour.")

# The product owner decides in plain words, the spec carries the binding code name, the decisions check
# (``review.spec_decisions``) checks the code against it.
SPEC_IDENTIFIER_RULE = (
    "Every Decisions entry that fixes a concrete value or a technology must name, in backticks, the code identifier "
    "or package that carries it (\"Grind setting starts at 15 (`grindSetting`)\", \"Persistence: drift/SQLite "
    "(`drift`)\"): the platform checks the code against that name. An entry without it is a finding of severity "
    '"medium" whose fix names the identifier or package to add.'
)

# Every code review checks where the change lives: a repository may hold several apps.
SCOPE_RULE = (
    "First check where the change lives: it must be in the part of the repository the work item and its "
    "specification are about (the app, package or module they name, for example the folder of the spec the work "
    "item points to). A change that builds the work item in another app or package, or changes an unrelated app, is "
    'a finding of severity "high" on its first such file whose fix names the right place.'
)

# A spec review (``checklist: "spec"``) judges a specification, not code, with the checks product owners need.
SPEC_REVIEW_RULE = (
    "The change under review is a specification, not code. Review it with this checklist and report every hit as a "
    "finding on the spec file and line: (1) a behaviour a developer needs that it leaves open: a default value, a "
    "threshold, a unit, an input or output format, an ordering, empty or missing data, an error case, a limit; "
    "(2) two statements that contradict each other, in the spec or against the work item; (3) every worked example: "
    "recompute it from the rule or formula it illustrates and report a wrong number with the correct one; (4) an "
    'acceptance criterion a test cannot check (vague words like "works", "fast" or "user-friendly", no expected '
    "value); (5) a ticket that depends on something no ticket delivers, or whose criteria name no section; (6) a "
    "product with a user interface whose spec has no UI and design section, or a screen without its elements and "
    "states, "
    "or whose UI and design section leaves the look to guesswork: a visual anchor, hero or placeholder described only "
    'as "a coloured area" (not how it is drawn and how it varies per item), or no "Look and feel" list of checks a '
    "reviewer can tick on a screenshot. "
    'Severity: "high" for a contradiction or a wrong example that changes what gets built, "medium" for an open '
    'behaviour, an untestable criterion that a developer could not decide alone, or a look left to guesswork (check '
    '6), "low" for wording, a rounding '
    'difference that changes no outcome (a contrast ratio that passes either way), and a detail the stories can '
    'decide by the simplest option consistent with the spec. Where the diff shows only part of the file, judge that '
    'part and its consistency '
    "with the lines shown around it."
)

# Two stages for a spec review: stage 1 walks the checklist without judging, stage 2 judges every candidate.
SPEC_AUDIT_RULE = (
    "Do not judge the change yet: this is the first pass of a two-step review. Walk through the specification in "
    "the change section by section and apply each of the five checks to every section; then go through every "
    "numbered or lettered point of every product owner answer, if there are any. Answer with one JSON object only: "
    '{"audit": [{"check": <1 to 5>, "file": "<path>", "line": <line number>, "quote": "<the words in the change, at '
    'most 20>", "issue": "<what is open, contradicts or is wrong; for an example the correct number>"}], '
    '"answers": [{"answer": <n>, "point": "<A, 3, ...>", "done": true or false, "evidence": "<the line or words in '
    'the change that show it, or what is missing>"}]}. List every candidate, also an uncertain one; the second pass '
    "drops the ones the change does not support. Empty lists when there is nothing."
)
SPEC_JUDGE_RULE = (
    "The task ends with the audit of a first pass over this change. Check every audit candidate and every answer "
    "point against the change itself: keep a candidate as a finding only when the quoted words are in the change and "
    "the issue holds; drop it otherwise (a part that is unchanged and correct is not missing just because the diff "
    "does not show it). A point marked not done is a finding only when the change really lacks it. Then answer with "
    "the verdict object."
)

# The PR review bot: a finding may carry the replacement code, which the pull request shows as a
# one-click suggestion. Only a review node with ``suggestions: true`` asks for it; the answer contract stays as it is.
SUGGESTION_RULE = (
    'Where the fix is a concrete code change of a few lines in the changed file, add to the finding "suggestion": the '
    'complete new text of the lines "start_line" to "line" of that file as they should read after the fix (exact '
    'indentation, no diff markers, no explanation), and "start_line": the first line it replaces (equal to "line" for '
    'one line). The range is exact: every line it rewrites lies in it, so applying it leaves no old line behind. '
    'Leave both out when the fix is not a small local replacement.'
)
WALKTHROUGH_RULE = (
    'Also add "walkthrough": a list with one entry {"file": "<path>", "change": "<what this change does in the file, '
    'at most one sentence>"} for every changed file, in the order of the diff.'
)

# The PR review bot's acceptance table: a review node with ``acceptance: true`` asks
# for one line per acceptance criterion of the work item. Informative only: it never changes the verdict or a gate;
#a criterion the change breaks is still a finding (SEVERITY_RULE).
ACCEPTANCE_RULE = (
    'Also add "acceptance": one entry {"criterion": "<the acceptance criterion, short>", "status": "covered" or '
    '"partial" or "missing", "evidence": "<the file:line or the test that shows it, or what is missing>"} for every '
    "acceptance criterion the work item states, in its order. When a section \"acceptance criteria\" lists them, "
    "give exactly one entry for every listed criterion, in that order, each criterion starting with its id (AC1, "
    "AC2, ...). An empty list when the work item states none."
)
ACCEPTANCE_FOLLOW_UP = (
    'In that JSON object also add "acceptance": one entry {"criterion", "status", "evidence"} for every criterion the '
    'section "acceptance criteria" lists (they may have changed since the previous review), as described above.'
)
MAX_ACCEPTANCE, MAX_ACCEPTANCE_TEXT = 30, 300
ACCEPTANCE_STATES = ("covered", "partial", "missing")

CONFIRMED_CONTRACT_RULE = (
    "The confirmed acceptance criteria and confirmed tests in the test facts are what a person agreed the change "
    "must do. Judge the change against them: never ask for a change that contradicts a confirmed criterion, or that "
    "changes or removes a confirmed test or a helper it uses, unless a person confirms a new contract."
)


@dataclass(frozen=True, slots=True)
class Finding:
    severity: str
    file: str
    line: int
    fix: str
    #: Stable over the rounds of one node (``F1``, ``F2``, ...): a follow-up review answers each previous id
    #: (``convergence``). Empty on a finding parsed from a first answer before the runner numbers it.
    id: str = ""
    #: The replacement of the lines ``start_line``..``line`` (``SUGGESTION_RULE``); empty without one. Kept after
    #: ``id``: other code builds findings positionally ``Finding(severity, file, line, fix, id)``.
    suggestion: str = ""
    start_line: int = 0
    #: What people answered in the finding's thread on the pull request (the PR review bot): the next
    #: follow-up weighs them (``convergence.FOLLOW_UP_RULE``: ``withdrawn`` without new evidence). Empty elsewhere.
    replies: tuple[str, ...] = ()

    def render(self) -> str:
        return f"{self.file}:{self.line} [{self.severity}] {self.fix}"

    def to_dict(self) -> dict[str, Any]:
        record = asdict(self)
        record["replies"] = list(self.replies)
        return {key: value for key, value in record.items()
                if value or key not in ("id", "suggestion", "start_line", "replies")}


@dataclass(frozen=True, slots=True)
class Verdict:
    verdict: str
    summary: str
    findings: tuple[Finding, ...]
    assumptions: tuple[str, ...] = ()
    walkthrough: tuple[tuple[str, str], ...] = ()
    acceptance: tuple[tuple[str, str, str], ...] = ()

    @property
    def passed(self) -> bool:
        return self.verdict == VERDICT_PASS

    def to_dict(self) -> dict[str, Any]:
        record = {"verdict": self.verdict, "summary": self.summary,
                  "findings": [finding.to_dict() for finding in self.findings]}
        record = {**record, "assumptions": list(self.assumptions)} if self.assumptions else record
        if self.walkthrough:
            record["walkthrough"] = [{"file": file, "change": change} for file, change in self.walkthrough]
        if self.acceptance:
            record["acceptance"] = [{"criterion": criterion, "status": status, "evidence": evidence}
                                    for criterion, status, evidence in self.acceptance]
        return record


def _finding(raw: Any) -> Finding | None:
    if not isinstance(raw, dict):
        return None
    severity, file, fix, line = (str(raw.get("severity") or "").strip().lower(), str(raw.get("file") or "").strip(),
                                 str(raw.get("fix") or "").strip(), raw.get("line"))
    if severity not in SEVERITIES or not fix:
        return None
    # A finding without a line concerns the file or the work item as a whole: line 1, file "(work item)".
    if type(line) is not int or line < 1:
        line = 1
    suggestion, start = _suggestion(raw, line)
    return Finding(severity, (file or "(work item)")[:300], line, fix, str(raw.get("id") or "").strip()[:20],
                   suggestion, start, _replies(raw.get("replies")))


MAX_REPLIES, MAX_REPLY_CHARS = 3, 500


def _replies(raw: Any) -> tuple[str, ...]:
    if not isinstance(raw, list):
        return ()
    texts = [str(item).strip()[:MAX_REPLY_CHARS] for item in raw if isinstance(item, str) and item.strip()]
    return tuple(texts[-MAX_REPLIES:])


def _suggestion(raw: dict, line: int) -> tuple[str, int]:
    text = raw.get("suggestion")
    if not isinstance(text, str) or not text.strip():
        return "", 0
    start = raw.get("start_line")
    start = start if type(start) is int and 1 <= start <= line else line
    return text, start


def finding_from(raw: Any) -> Finding | None:
    return _finding(raw)


def parse_verdict(answer: Any) -> Verdict | None:
    if not isinstance(answer, dict):
        return None
    verdict = str(answer.get("verdict") or "").strip().lower()
    raw = answer.get("findings") if answer.get("findings") is not None else []
    if verdict not in (VERDICT_PASS, VERDICT_CHANGES) or not isinstance(raw, list):
        return None
    findings = [_finding(item) for item in raw]
    if any(item is None for item in findings):
        return None
    blocking = [item for item in findings if item.severity in BLOCKING_SEVERITIES]
    if (verdict == VERDICT_PASS and blocking) or (verdict == VERDICT_CHANGES and not findings):
        return None
    return Verdict(verdict, str(answer.get("summary") or "").strip(), tuple(findings),
                   _assumptions(answer.get("assumptions")), _walkthrough(answer.get("walkthrough")),
                   _acceptance(answer.get("acceptance")))


def _acceptance(raw: Any) -> tuple[tuple[str, str, str], ...]:
    if not isinstance(raw, list):
        return ()
    rows = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        criterion = str(item.get("criterion") or "").strip()[:MAX_ACCEPTANCE_TEXT]
        status = str(item.get("status") or "").strip().lower()
        if criterion and status in ACCEPTANCE_STATES:
            rows.append((criterion, status, str(item.get("evidence") or "").strip()[:MAX_ACCEPTANCE_TEXT]))
    return tuple(rows[:MAX_ACCEPTANCE])


def _walkthrough(raw: Any) -> tuple[tuple[str, str], ...]:
    if not isinstance(raw, list):
        return ()
    entries = [(str(item.get("file") or "").strip(), str(item.get("change") or "").strip())
               for item in raw if isinstance(item, dict)]
    return tuple((file, change) for file, change in entries if file and change)


def _assumptions(raw: Any) -> tuple[str, ...]:
    if not isinstance(raw, list):
        return ()
    texts = [str(item).strip() for item in raw if isinstance(item, (str, int, float)) and str(item).strip()]
    return tuple(texts)


def verdict_from_record(record: Any) -> Verdict | None:
    return parse_verdict(record) if isinstance(record, dict) else None


__all__ = ["ACCEPTANCE_FOLLOW_UP", "ACCEPTANCE_RULE", "ANSWER_CONTRACT", "SEVERITY_RULE", "finding_from",
           "ASSUMPTIONS_RULE", "SCOPE_RULE",
           "BLOCKING_SEVERITIES",
           "CONFIRMED_CONTRACT_RULE", "PO_ANSWERS_RULE", "SEVERITIES", "SPEC_AUDIT_RULE", "SPEC_DECISIONS_RULE",
           "SPEC_JUDGE_RULE", "SPEC_REVIEW_RULE", "SUGGESTION_RULE", "VERDICT_CHANGES", "WALKTHROUGH_RULE",
           "SPEC_IDENTIFIER_RULE", "VERDICT_PASS", "Finding", "Verdict", "parse_verdict", "verdict_from_record",
           "ROOT_CAUSE_RULE"]
