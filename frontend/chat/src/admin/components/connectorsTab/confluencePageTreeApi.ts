// One level of a Confluence space's page tree (delivery 5): GET .../connectors/confluence/page-tree, global or
// a Workspace's (.../projects/{id}/connectors/...). Read-only, read with the saved connection that serves the space
// in that scope; failures carry a fixed code.
import type { PageNode } from "./confluencePagePickerModel";

export type ReadJson = <T>(url: string, init?: RequestInit) => Promise<T>;

export type Level = { pages: PageNode[]; nextStart: number | null; loading: boolean; error: string | null };

export const PAGE_TREE_URL = "/admin/chat/api/panel/connectors/confluence/page-tree";

/** The tree endpoint of the global entry (null) or of a Workspace. */
export function pageTreeUrl(projectId: string | null): string {
  return projectId === null
    ? PAGE_TREE_URL
    : `/admin/chat/api/panel/projects/${encodeURIComponent(projectId)}/connectors/confluence/page-tree`;
}

export function levelKey(space: string, parent: string | null): string {
  return `${space}:${parent ?? ""}`;
}

export function levelUrl(space: string, parent: string | null, start: number, treeUrl = PAGE_TREE_URL): string {
  const params = new URLSearchParams({ space_key: space, start: String(start) });
  if (parent) params.set("parent_id", parent);
  return `${treeUrl}?${params.toString()}`;
}

const MESSAGES: Record<string, string> = {
  connection_not_configured_for_scope: "No saved connection serves this space. Add it to the allowed spaces, save, then open it again.",
  connector_not_configured: "Save and test the Confluence connector first.",
  connector_not_enabled_in_workspace: "Enable Confluence for this Workspace and save access first.",
  confluence_unauthorized: "Confluence refused this account for the space or page.",
  confluence_page_not_found: "Confluence does not know this space or page, or this account cannot see it.",
  confluence_unavailable: "Confluence could not be read right now.",
};

/** The message of a failed level read, from its fixed code when the server sent one. */
export function levelError(error: unknown): string {
  // readJson (adminPanelHelpers) carries the server's fixed refusal code and its message.
  const code = typeof (error as { code?: unknown } | null)?.code === "string" ? (error as { code: string }).code : "";
  if (MESSAGES[code]) return MESSAGES[code];
  return error instanceof Error && error.message ? error.message : "The pages could not be loaded.";
}

export async function readLevel(
  readJson: ReadJson, space: string, parent: string | null, start: number, treeUrl = PAGE_TREE_URL,
) {
  const payload = await readJson<{ pages?: unknown; next_start?: unknown }>(levelUrl(space, parent, start, treeUrl));
  const pages = Array.isArray(payload.pages)
    ? payload.pages.filter((page): page is PageNode => Boolean(page) && typeof page.id === "string" && typeof page.title === "string")
    : [];
  return { pages, nextStart: typeof payload.next_start === "number" ? payload.next_start : null };
}
