"""Code-question verdicts: an answer has its facts, and every citation is the repository at its commit.

``Verdict`` holds only counts, file paths, URLs and missing fact tokens, never source text, so it can
be printed as the check's fact line.

- ``judge_search``: REST hybrid ``knowledge_search`` hits. The facts must appear across the hits'
  text; every hit's ``source_url`` must be a pinned blob URL of the repository, and one of them must
  be a file the answer is grounded in.
- ``judge_chat``: a chat answer. The facts must appear in the answer; it must carry at least one
  link, every link must be a pinned blob URL of the repository, one must be a grounding file, and the
  turn must have used a Knowledge tool.
- ``judge_impact``: the step 4 answer and its ``knowledge_code_impact`` results.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .questions import Question
from .repos import OUTSIDE, PINNED, PinnedRepo, citation_counts, classify, links

_MAX_URLS_SHOWN = 3


@dataclass
class Verdict:
    ok: bool
    parts: list[str] = field(default_factory=list)

    @property
    def fact(self) -> str:
        return "; ".join(self.parts)


def _missing(patterns: tuple[str, ...], text: str) -> list[str]:
    return [pattern for pattern in patterns if not re.search(pattern, text, re.IGNORECASE)]


def _citation_parts(citations, counts: dict[str, int]) -> list[str]:
    parts = [f"links {len(citations)} " + " ".join(f"{key} {value}" for key, value in counts.items())]
    pinned = sorted({citation.path for citation in citations if citation.kind == PINNED})
    if pinned:
        parts.append("pinned files " + ",".join(pinned[:_MAX_URLS_SHOWN]))
    others = [citation.url for citation in citations if citation.kind != PINNED]
    if others:
        parts.append("not pinned " + " ".join(others[:_MAX_URLS_SHOWN]))
    return parts


def judge_search(question: Question, payload: object, repo: PinnedRepo, tree: frozenset[str]) -> Verdict:
    hits = (payload or {}).get("evidence") if isinstance(payload, dict) else None
    if not isinstance(hits, list):
        return Verdict(False, ["no evidence list"])
    states = (payload or {}).get("mode_states") or {}
    citations = [classify(str(hit.get("source_url") or "no-link"), repo, tree) for hit in hits]
    counts = citation_counts(citations)
    # Indexed code identifiers may be in the file/symbol locator of an import span.
    # Ground truth independently confirms each declared entity at the pinned commit.
    retrieved = "\n".join(
        " ".join(str(hit.get(key) or "") for key in ("text", "source_title", "section_path")) for hit in hits
    )
    missing = _missing(question.facts, retrieved)
    grounded = any(citation.kind == PINNED and citation.path in question.files for citation in citations)
    ok = bool(hits) and not missing and grounded and counts[PINNED] == len(citations)
    parts = [f"hits {len(hits)} modes {dict(sorted(states.items()))}", f"facts missing {missing or 'none'}",
             f"grounding file cited {grounded}"]
    return Verdict(ok, parts + _citation_parts(citations, counts))


def judge_chat(
    question: Question, answer: str, tools: list[str], repo: PinnedRepo, tree: frozenset[str]
) -> Verdict:
    citations = [classify(url, repo, tree) for url in links(answer)]
    counts = citation_counts(citations)
    missing = _missing(question.facts, answer)
    grounded = any(citation.kind == PINNED and citation.path in question.files for citation in citations)
    knowledge_used = any(name.startswith("knowledge_") for name in tools)
    ok = (bool(answer) and not missing and grounded and knowledge_used and bool(citations)
          and counts[PINNED] == len(citations))
    parts = [f"tools {','.join(dict.fromkeys(tools)) or 'none'}", f"facts missing {missing or 'none'}",
             f"grounding file cited {grounded}"]
    return Verdict(ok, parts + _citation_parts(citations, counts))


def judge_impact(answer: str, results: list[dict], repo: PinnedRepo, tree: frozenset[str]) -> list[tuple[str, Verdict]]:
    """Three verdicts: the tool ran on the pinned commit, its locations are real files, the answer links them."""
    verdicts: list[tuple[str, Verdict]] = []
    ok_results = [result for result in results if result.get("state") == "ok"]
    best = max(ok_results, key=lambda result: int(result.get("impacted_fact_count") or 0), default=None)
    states = ",".join(str(result.get("state")) for result in results) or "not called"
    if best is None:
        verdicts.append(
            ("knowledge_code_impact answered ok on the pinned commit", Verdict(False, [f"states {states}"]))
        )
        verdicts.append(("impact locations are files of the repository", Verdict(False, ["no ok result"])))
    else:
        commit = str(best.get("commit") or "none")
        facts = int(best.get("impacted_fact_count") or 0)
        verdicts.append((
            "knowledge_code_impact answered ok on the pinned commit",
            Verdict(commit == repo.sha and facts > 0 and int(best.get("elements_scanned") or 0) > 0,
                    [f"states {states}", f"commit {commit[:12]}", f"elements_scanned {best.get('elements_scanned')}",
                     f"facts_considered {best.get('facts_considered')}", f"impacted_fact_count {facts}"]),
        ))
        paths = [str(at).split(":", 1)[0] for item in best.get("impact") or [] for at in item.get("at") or []]
        unknown = sorted({path for path in paths if path not in tree})
        verdicts.append((
            "impact locations are files of the repository",
            Verdict(bool(paths) and not unknown,
                    [f"locations {len(paths)}", "files " + ",".join(sorted(set(paths))[:5]),
                     f"unknown {unknown or 'none'}"]),
        ))
    citations = [classify(url, repo, tree) for url in links(answer)]
    counts = citation_counts(citations)
    # Change facts cite their own sources (migration guide, release notes); repository files must be pinned.
    into_repo = [citation for citation in citations if citation.kind != OUTSIDE]
    named = sorted(path for path in tree if path.count("/") and path in answer)
    ok = counts[PINNED] > 0 and counts[PINNED] == len(into_repo)
    verdicts.append((
        "the impact answer links real repository files at the pinned commit",
        Verdict(ok, [f"files named in text {len(named)}"] + _citation_parts(citations, counts)),
    ))
    return verdicts


__all__ = ["Verdict", "judge_chat", "judge_impact", "judge_search"]
