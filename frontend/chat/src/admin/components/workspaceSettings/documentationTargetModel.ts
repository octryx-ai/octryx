// The server matches only Knowledge sources' connector_key, so a named connection is not a valid value.
// The server merges config one level deep, so the body carries only feature_documentation; "" means not set.

import { ROOT_PAGE_ID, SPACE_KEY } from "../workspaceKnowledge/confluencePageTree";

export const DOC_KEY = "feature_documentation";

export type DocTarget = { spaceKey: string; parentPageId: string; connectorKey: string; autoPublish: boolean };
export type DocTargetField = keyof DocTarget;
export type DocTargetErrors = Partial<Record<DocTargetField | "general", string>>;

export const EMPTY_DOC_TARGET: DocTarget = { spaceKey: "", parentPageId: "", connectorKey: "", autoPublish: false };

const text = (value: unknown) => (typeof value === "string" ? value.trim() : typeof value === "number" ? String(value) : "");

export function readDocTarget(raw: unknown): DocTarget {
  const holder = (raw ?? {}) as { config?: unknown };
  const config = (holder.config && typeof holder.config === "object" ? holder.config : raw ?? {}) as Record<string, unknown>;
  const stored = (config[DOC_KEY] && typeof config[DOC_KEY] === "object" ? config[DOC_KEY] : {}) as Record<string, unknown>;
  return {
    spaceKey: text(stored.confluence_space_key).toUpperCase(),
    parentPageId: text(stored.parent_page_id),
    connectorKey: text(stored.knowledge_connector_key),
    autoPublish: stored.auto_publish === true,
  };
}

export function docTargetProblems(draft: DocTarget): DocTargetErrors {
  const errors: DocTargetErrors = {};
  const space = draft.spaceKey.trim();
  const parent = draft.parentPageId.trim();
  if (space && !SPACE_KEY.test(space)) errors.spaceKey = "A space key has letters, digits or _ only, for example ENG or ~jdoe.";
  if (parent && !ROOT_PAGE_ID.test(parent)) errors.parentPageId = "A page id is the number in the page's address, for example 123456789.";
  if (!space && (parent || draft.connectorKey.trim() || draft.autoPublish)) {
    errors.spaceKey = "Name the space first: without it nothing is published.";
  }
  return errors;
}

export function docTargetWarnings(draft: DocTarget): Partial<Record<"parentPageId", string>> {
  if (draft.parentPageId.trim()) return {};
  if (draft.autoPublish) return { parentPageId: PARENT_MISSING_AUTO };
  if (draft.spaceKey.trim()) return { parentPageId: PARENT_MISSING };
  return {};
}

export function docTargetBody(draft: DocTarget): Record<string, Record<string, string | boolean>> {
  return {
    [DOC_KEY]: {
      confluence_space_key: draft.spaceKey.trim().toUpperCase(),
      parent_page_id: draft.parentPageId.trim(),
      knowledge_connector_key: draft.connectorKey.trim(),
      auto_publish: draft.autoPublish,
    },
  };
}

export const sameDocTarget = (a: DocTarget, b: DocTarget) =>
  a.spaceKey.trim().toUpperCase() === b.spaceKey.trim().toUpperCase() && a.parentPageId.trim() === b.parentPageId.trim()
  && a.connectorKey.trim() === b.connectorKey.trim() && a.autoPublish === b.autoPublish;

export type ConfluenceSource = { key: string; spaces: string[] };

export function confluenceSources(connectors: readonly { connector_key?: unknown; kind?: unknown; scope?: unknown }[]): ConfluenceSource[] {
  return connectors.flatMap((connector) => {
    const key = text(connector.connector_key);
    if (connector.kind !== "confluence" || !key) return [];
    const scope = (connector.scope ?? {}) as { spaces?: unknown; page_trees?: unknown };
    const spaces = [
      ...(Array.isArray(scope.spaces) ? scope.spaces : []),
      ...(Array.isArray(scope.page_trees) ? scope.page_trees.map((tree) => (tree as { space_key?: unknown } | null)?.space_key) : []),
    ].map((space) => text(space).toUpperCase()).filter(Boolean);
    return [{ key, spaces: [...new Set(spaces)] }];
  });
}

export function offeredSpaces(sources: readonly ConfluenceSource[], connectorKey: string): string[] {
  const chosen = sources.filter((source) => !connectorKey || source.key === connectorKey);
  return [...new Set(chosen.flatMap((source) => source.spaces))].sort();
}

export function docTargetSaveErrors(status: number, body: unknown): DocTargetErrors {
  const detail = (body as { detail?: unknown } | null)?.detail;
  const words = typeof detail === "string" ? detail : JSON.stringify(detail ?? "");
  if (status === 403) return { general: "Not saved: only a platform admin can change the documentation target." };
  if (status === 404) return { general: "Not saved: this Workspace no longer exists." };
  if (status === 400 || status === 422) {
    if (words.includes("auto_publish")) return { autoPublish: "The server did not accept this switch. Reload and try again." };
    if (words.includes("parent_page_id")) return { parentPageId: "The server did not accept this page id." };
    if (words.includes("confluence_space_key")) return { spaceKey: "The server did not accept this space key." };
    if (words.includes("knowledge_connector_key")) return { connectorKey: "The server did not accept this Knowledge source." };
    return { general: `Not saved: the server refused the documentation target${typeof detail === "string" && detail ? ` (${detail})` : ""}.` };
  }
  return { general: "Not saved: the server did not answer. Try again." };
}

export const DOC_TARGET_INTRO =
  "Publish spec, feature and epic pages automatically when a run starts. Octryx creates pages under the parent and "
  + "updates only pages it created; it never deletes, moves or writes to other spaces.";
export const AUTO_PUBLISH_HINT = "The run start is the approval: each run publishes its pages without asking.";
export const PARENT_HINT = "The number in the parent page's address (…/pages/123456789/…). Pages are created only under it.";
export const PARENT_MISSING = "Required: without a parent page nothing is published.";
export const PARENT_MISSING_AUTO = "Automatic publishing is on, but no parent page is set: runs will skip documentation.";
