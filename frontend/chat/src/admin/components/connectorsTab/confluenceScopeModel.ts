export const SPACES_FIELD = "confluence_allowed_spaces";
export const PAGES_FIELD = "confluence_allowed_pages";
export const CONFLUENCE_SCOPE_FIELDS = [SPACES_FIELD, PAGES_FIELD];
// Confluence's own space key rule (Source Sync's): letters, digits, "_", a leading "~" for personal spaces.
export const SPACE_RULE = { pattern: "~?[A-Za-z0-9_]{1,64}" };

export function connectionTested(
  connector: { tool_name?: string; configured?: boolean; health?: { status?: unknown } | null },
  testResults: Record<string, { ok?: unknown } | undefined> | undefined,
): boolean {
  if (!connector.configured) return false;
  const result = testResults?.[connector.tool_name ?? ""];
  if (result) return result.ok === true;
  return connector.health?.status === "ok";
}
