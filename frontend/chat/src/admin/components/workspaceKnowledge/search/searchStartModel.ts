// What Knowledge › Search shows before the first search instead of an empty area under the field. Two
// compact parts, both read from what the page already loads (the connectors and the documents list):
// the sources search reads with their last sync, and three example questions made from those sources' names. Recent
// searches are not shown: no server keeps a person's searches. Pure: no requests, no React.

import type { SourceConnector } from "../connectorTypes";
import type { KnowledgeSource } from "../workspaceKnowledgeTypes";
import { gitScopeSummary } from "../gitRepositoryScope";
import { originLabel } from "./searchFacets";
import { lastSyncAt, sourceName, sourceState, type SourceTone } from "../sources/sourceState";

// `reason`: why a source needs attention (its tooltip), else null.
export type StartSource = {
  key: string; name: string; origin: string; state: string; tone: SourceTone; at: number | null; reason: string | null;
};

export const START_SOURCE_LIMIT = 6;

/** The connected sources, at most START_SOURCE_LIMIT, the ones that need attention first, each with its state. */
export function startSources(connectors: SourceConnector[], schedulingOn = true, now = Date.now()): StartSource[] {
  const rank = (tone: SourceTone) => (tone === "warning" || tone === "danger" ? 0 : 1);
  return connectors
    .map((connector, index) => {
      const state = sourceState(connector, false, schedulingOn, now);
      return { index, row: { key: connector.connector_key, name: sourceName(connector), origin: originLabel(connector.kind),
        state: state.word, tone: state.tone, at: state.lastSyncAt, reason: state.reason } };
    })
    .sort((a, b) => rank(a.row.tone) - rank(b.row.tone) || a.index - b.index)
    .slice(0, START_SOURCE_LIMIT)
    .map(({ row }) => row);
}

// The shortest name a person would type for a source: a Confluence space or Jira project key, a repository's name,
// a cluster; else the source's own name.
function subjectOf(connector: SourceConnector): string {
  const scope = connector.scope ?? {};
  if (connector.kind === "git_repository") {
    const repository = gitScopeSummary(scope).repository;
    return repository.split("/").filter(Boolean).pop()?.replace(/\.git$/, "") || sourceName(connector);
  }
  if (connector.kind === "kubernetes" && scope.cluster) return scope.cluster;
  const keys = scope.spaces ?? scope.project_keys ?? [];
  return keys[0] || sourceName(connector);
}

const QUESTION: Record<string, (subject: string) => string> = {
  confluence: (subject) => `What is documented in ${subject}?`,
  jira: (subject) => `Which ${subject} issues are still open?`,
  git_repository: (subject) => `How is ${subject} configured?`,
  servicenow: (subject) => `Which known issues are described in ${subject}?`,
  kubernetes: (subject) => `Which services run in ${subject}?`,
};

const isUpload = (source: KnowledgeSource) => {
  const origin = source.origin as { type?: unknown } | null | undefined;
  return !origin || origin.type !== "connector";
};

/**
 * Three example questions, each about a different source that has something to find (synced at least once), then
 * about uploaded documents by their titles. Fewer when the workspace has fewer sources; none when it has none.
 */
export function exampleQuestions(connectors: SourceConnector[], documents: KnowledgeSource[] = [], count = 3): string[] {
  const questions: string[] = [];
  const add = (question: string) => {
    if (questions.length < count && !questions.includes(question)) questions.push(question);
  };
  for (const connector of connectors) {
    const nothingYet = lastSyncAt(connector) === null && !connector.served_items;
    if (connector.state === "paused" || nothingYet) continue;
    const ask = QUESTION[connector.kind] ?? ((subject: string) => `What is in ${subject}?`);
    add(ask(subjectOf(connector)));
  }
  for (const document of documents.filter(isUpload)) {
    const title = document.display_title.trim().replace(/\.[a-z0-9]{1,5}$/i, "");
    if (title) add(`What does ${title} say?`);
  }
  return questions;
}
