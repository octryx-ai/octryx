// Workspace settings › Knowledge › "Documentation target": where runs publish feature documentation (project config
// `feature_documentation`, backend workflow_runs/documentation/page.py `documentation_settings`). Pure: no React.
//
// - `confluence_space_key` (required to publish): the space; the server upper-cases it.
// - `parent_page_id` (required to publish since): the page new pages go under. Without it the run's `docs` step
//   skips with `no_parent_page` (documentation/auto_pages.py) and the confirmed publication blocks (target.py).
// - The Confluence connection is not a field: the server routes the space to its named connection
//   (`named_connections`, `served_confluence`), whose space allowlist applies.
// - `knowledge_connector_key` (optional): the Workspace's Confluence Knowledge source that syncs the page; the server
//   matches it against the Knowledge sources' `connector_key` only (documentation/knowledge.py `covering_source`), so a
//   named connection is not a valid value. Empty: the source whose scope covers the space or the parent's tree.
// - `auto_publish` (default off): runs publish spec and feature pages unattended under the parent.
//
// PUT /api/v1/projects/<id>/config merges top-level keys and a dict value one level deep
// (admin_project_config_service.apply_project_config_patch), so the body carries only `feature_documentation` and
// its other keys (e.g. `audience_proof`) stay. An empty field is sent as "" (the server reads it as not set).

import { ROOT_PAGE_ID, SPACE_KEY } from "../workspaceKnowledge/confluencePageTree";

export const DOC_KEY = "feature_documentation";

export type DocTarget = { spaceKey: string; parentPageId: string; connectorKey: string; autoPublish: boolean };
export type DocTargetField = keyof DocTarget;
export type DocTargetErrors = Partial<Record<DocTargetField | "general", string>>;

export const EMPTY_DOC_TARGET: DocTarget = { spaceKey: "", parentPageId: "", connectorKey: "", autoPublish: false };

const text = (value: unknown) => (typeof value === "string" ? value.trim() : typeof value === "number" ? String(value) : "");

/** The stored target of a project config (`{config: {...}}` or the config itself). */
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

/** The draft's problems at their fields; empty when it can be saved. */
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

/** Non-blocking warnings: the target saves, but runs will skip documentation. */
export function docTargetWarnings(draft: DocTarget): Partial<Record<"parentPageId", string>> {
  if (draft.parentPageId.trim()) return {};
  if (draft.autoPublish) return { parentPageId: PARENT_MISSING_AUTO };
  if (draft.spaceKey.trim()) return { parentPageId: PARENT_MISSING };
  return {};
}

/** The PUT body: only `feature_documentation`, its four keys; other config keys and sub-keys stay. */
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

/** The Workspace's Confluence Knowledge sources and the spaces their scope names (whole spaces and page trees). */
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

/** The spaces to offer for the chosen source (all sources' spaces when none is chosen). */
export function offeredSpaces(sources: readonly ConfluenceSource[], connectorKey: string): string[] {
  const chosen = sources.filter((source) => !connectorKey || source.key === connectorKey);
  return [...new Set(chosen.flatMap((source) => source.spaces))].sort();
}

/** A refused save in words, at its field where the server names one. */
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
