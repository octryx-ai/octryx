"""Response-quality guard detection policy.

Single reviewable home for the LANGUAGE TABLES used by the assistant
response-quality guards: transitional/filler-phrase suppression, coding
clarification detection, and knowledge-negation detection, in one policy
module, mirroring ``app.services.context_routing_policy`` (explicit-first
decision): detection features are reviewable policy, not anonymous inline
heuristics.

Only the language tables live here. The guard LOGIC — scoring, loop-state
checks, suppression decisions — stays anchored on runtime state in the guard
modules above, which import these tables.
"""

from __future__ import annotations

import re

# --- Transitional/filler phrase detection --------------------------------

CODING_INTENT_ONLY_PATTERN = re.compile(
    r"(^|\b)("
    r"i will|i'll|let me|i am going to|next i will|now i will"
    r")\b",
    re.IGNORECASE,
)

TRANSITIONAL_ASSISTANT_PATTERN = re.compile(
    r"\b("
    r"let me(?! know\b)\b|"
    r"i(?: am|'m) searching\b|"
    r"try again\b|"
    r"try once more\b|"
    r"i need to\b|"
    r"i need\b|"
    r"i will\b|"
    r"i'll\b|"
    r"now i'll\b|"
    r"next i'll\b|"
    # Announcement-only answers on catalog turns ("I select the matching
    # workflow." and nothing else) do not finish a turn.
    r"i(?: am|'m)? (?:select|choos|pick)\w*\b|"
    r"can you confirm\b|"
    r"i can (?:now )?(?:search|look|check|inspect|review|find|analy[sz]e|examine|prepare|read|continue|"
    r"gather|collect|fetch|pull)\b|"
    r"i(?:'ll| will) (?:now )?(?:update|create|write|save|persist|sync|add)\b|"
    # MiniMax-M3 announcement-only turns announced a tool call that never
    # materialized; without these tokens the announcement ended the turn.
    r"i start by\b|"
    r"i(?: am|'m) starting\b|"
    r"allow me to\b"
    r")",
    re.IGNORECASE,
)
TRANSITIONAL_SEGUE_PATTERN = re.compile(
    r"(?:^|[\.\n]\s*)("
    r"now let me\b|"
    r"let me(?! know\b)\b|"
    r"next i(?:'ll| will)\b|"
    r"i(?:'ll| will) now\b"
    r")",
    re.IGNORECASE,
)
TRANSITIONAL_RESPONSE_HINT_TERMS = (
    " use ",
    " use",
    "search",
    "look",
    "check",
    "inspect",
    "try",
    "retry",
    "review",
    "find",
    "analy",
    "examin",
    "prepare",
    "read",
    "continu",
    "gather",
    "collect",
    "fetch",
    "pull",
    "load",
    "utiliz",
    "update",
    "create",
    "write",
    "save",
    "persist",
    "sync",
    "add",
    "confirm",
    "now let me",
    # Workflow-selection announcements (MiniMax-M3 textual tool-call flake):
    # the transitional sentence names the workflow instead of an action verb.
    "workflow",
)
TRANSITIONAL_ACTION_MARKERS = (
    "read",
    "continue",
    "check",
    "inspect",
    "examine",
    "review",
    "collect",
    "gather",
    "look",
    "search",
    "find",
    "fetch",
    "pull",
    "analy",
)
TRANSITIONAL_SUBJECT_MARKERS = (
    "let me",
    "i'll",
    "i will",
    "now i",
    "first i",
)
TRANSITIONAL_CONFIRMATION_PATTERN = re.compile(
    r"\b("
    r"would you like me to continue\b|"
    r"would you like me to proceed\b|"
    r"shall i continue\b|"
    r"shall i proceed\b|"
    r"ready to proceed\b|"
    r"ready to continue\b"
    r")",
    re.IGNORECASE,
)
# Sentences that offer next steps to the user instead of announcing an action
# the assistant takes now ("If you want to continue, tell me …", "For example,
# I can search Jira …"). A complete answer that ends with such an offer is not
# a transition (otherwise "For example, I can search Jira …" matches
# ``i can search`` and the answer is suppressed until the run stops). The transition check ignores these
# sentences; an announcement elsewhere in the reply is still caught. Matched
# per sentence, anchored at the sentence start, or as a trailing conditional.
OFFER_SENTENCE_PATTERN = re.compile(
    r"^\s*(?:"
    r"if you(?:'d| would)? (?:want|like|prefer|wish|need)\b|"
    r"if (?:needed|helpful|that helps|useful|required)\b|"
    r"should you\b|"
    r"let me know\b|"
    r"tell me\b|"
    r"just (?:ask|say|tell me|let me know)\b|"
    r"feel free\b|"
    r"(?:for example|for instance|alternatively|otherwise|also|additionally),?\s+i (?:can|could)\b|"
    r"i (?:can|could) also\b"
    r")"
    r"|(?:,|\s)\s*if you(?:'d| would)? (?:want|like|prefer|wish)\b[^.!?]*[.!?]?\s*$",
    re.IGNORECASE,
)

# --- Placeholder (non-substantive) reply detection -----------------------
# A short reply is a placeholder only when its content is one: a waiting
# phrase or filler, never because it is short. Matched against the reply
# lowercased with punctuation removed and whitespace collapsed.
PLACEHOLDER_REPLY_PHRASES = frozenset(
    {
        "working on it",
        "im working on it",
        "i am working on it",
        "on it",
        "one moment",
        "one moment please",
        "just a moment",
        "a moment",
        "moment",
        "one sec",
        "just a sec",
        "hold on",
        "please wait",
        "wait",
        "processing",
        "thinking",
        "loading",
        "in progress",
        "stand by",
        "hmm",
        "hm",
        "uh",
        "um",
    }
)
# Bare acknowledgements: a placeholder when the user asked for work, a real
# answer when the user asked for exactly this short reply (see
# SHORT_REPLY_REQUEST_PATTERN).
ACKNOWLEDGEMENT_REPLY_PHRASES = frozenset(
    {
        "ok",
        "okay",
        "k",
        "sure",
        "alright",
        "all right",
        "got it",
        "understood",
        "noted",
        "will do",
    }
)
# The user explicitly asked for a short or exact reply ("Reply only with the
# word OK.", "reply with yes or no", "answer in one word").
SHORT_REPLY_REQUEST_PATTERN = re.compile(
    r"\b(?:"
    r"(?:answer|reply|respond|say|write)\s+(?:only|just)\b|"
    r"(?:only|just)\s+(?:answer|reply|respond|say|write)\b|"
    r"(?:answer|reply|respond)\s+with\s+(?:only\s+|just\s+)?(?:a\s+single|one|the\s+word|a\s+word|yes|no|ok)\b|"
    r"(?:in|with)\s+(?:a\s+single|one)\s+word\b|"
    r"one[- ]word\s+(?:answer|reply|response)\b|"
    r"yes\s*(?:/|or)\s*no\b|"
    r"nothing\s+(?:else|more)\b"
    r")",
    re.IGNORECASE,
)

# Markers a repeated-clause response must contain to count as a repetitive
# transition (read by ``looks_like_repetitive_transition``).
REPETITIVE_TRANSITION_MARKERS = (
    "details",
    "repositor",
)

# --- Knowledge-negation and synthesized-evidence detection ----------------

# Matches negated knowledge-authorship claims.
NEGATIVE_KNOWLEDGE_AUTHORSHIP_LINE_PATTERN = re.compile(
    r"(?i)\b(?:no|not|none|without)\b.*\bknowledge(?:\s+base)?\b.*\bauthor(?:ed|ship)?\b"
    r"|\bknowledge(?:\s+base)?\b.*\b(?:no|not|none|without)\b.*\bauthor(?:ed|ship)?\b"
    r"|\bknowledge(?:\s+base)?\b.*\bauthor(?:ed|ship)?\b.*\b(?:no|not|none|without)\b"
)
# A synthesized knowledge-user-evidence line (e.g. "Knowledge base user evidence:
# `source_people` found 12 knowledge entries.").
KNOWLEDGE_USER_EVIDENCE_LINE_PATTERN = re.compile(
    r"Knowledge[- ]base user evidence:\s*`source_people`\s*found\s+(\d+)\s+Knowledge entries",
    re.IGNORECASE,
)
# "Sources:" bullet label in synthesized evidence.
EVIDENCE_SOURCE_LABEL_LINE_PATTERN = re.compile(r"(?im)^\s*-\s*Sources:\s*([^\n.]+)")

# --- Coding clarification detection ---------------------------------------

# Focused clarification questions: a question, a clarification marker, and a
# named blocker must all be present.
CLARIFICATION_MARKER_PATTERN = re.compile(
    r"\b("
    r"clarification|clarify|question|questions|please confirm|please provide"
    r")\b",
    re.IGNORECASE,
)
CLARIFICATION_BLOCKER_PATTERN = re.compile(
    r"\b("
    r"repository|repo|branch|parent[- ]?pom|dependency|dependencies|version|versions|"
    r"private|internal|enterprise|sb-auto|maven|gradle|breaking[- ]change|acceptance|"
    r"jenkins"
    r")\b",
    re.IGNORECASE,
)
CLARIFICATION_QUESTION_PATTERN = re.compile(
    r"(\?|(?:^|\n)\s*(?:\d+\.|[-*])\s+.*\b(?:please|which|what|confirm))",
    re.IGNORECASE,
)
