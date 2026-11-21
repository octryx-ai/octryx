import {
  parseLimitField,
  parsePages,
  splitLines,
  stringifyLimitField,
  stringifyPages,
  stringifyRepos,
  stringifySpaces,
  stringifyStrings,
} from "./projectConnectorLimitCodec";

export type ProjectConnectorAccess = {
  connector_name: string;
  label: string;
  description: string;
  limit_fields: string[];
  global_configured: boolean;
  global_active: boolean;
  project_enabled: boolean;
  project_limits: Record<string, unknown>;
  inherited_limits: Record<string, unknown>;
  effective_limits: Record<string, unknown>;
  inherits_global_limits: boolean;
};

export type ProjectConnectorAccessResponse = {
  project_id: string;
  connectors: ProjectConnectorAccess[];
};

export type ConnectorDraft = {
  enabled: boolean;
  jiraProjects: string;
  confluenceSpaces: string;
  confluencePages: string;
  // The stored page entries: the one-line-per-page text cannot show subtrees, excludes or whole spaces, so a
  // save keeps them from here (delivery 5).
  confluencePageEntries: Array<Record<string, unknown>>;
  bitbucketRepos: string;
  genericLimits: Record<string, string>;
};

export const EMPTY_DRAFT: ConnectorDraft = {
  enabled: false,
  jiraProjects: "",
  confluenceSpaces: "",
  confluencePages: "",
  confluencePageEntries: [],
  bitbucketRepos: "",
  genericLimits: {},
};

export const KNOWN_LIMIT_FIELDS = new Set([
  "jira_allowed_projects",
  "confluence_allowed_spaces",
  "confluence_allowed_pages",
  "bitbucket_allowed_repos",
]);

export function draftFromAccess(
  access: ProjectConnectorAccess,
): ConnectorDraft {
  const limits = access.project_limits || {};
  const genericLimits = Object.fromEntries(
    (access.limit_fields || [])
      .filter((fieldName) => !KNOWN_LIMIT_FIELDS.has(fieldName))
      .map((fieldName) => [
        fieldName,
        stringifyLimitField(fieldName, limits[fieldName]),
      ]),
  );
  return {
    ...EMPTY_DRAFT,
    enabled: access.project_enabled,
    jiraProjects: stringifyStrings(limits.jira_allowed_projects),
    confluenceSpaces: stringifySpaces(limits.confluence_allowed_spaces),
    confluencePages: stringifyPages(limits.confluence_allowed_pages),
    confluencePageEntries: Array.isArray(limits.confluence_allowed_pages)
      ? limits.confluence_allowed_pages.filter(
          (entry): entry is Record<string, unknown> => Boolean(entry) && typeof entry === "object",
        )
      : [],
    bitbucketRepos: stringifyRepos(limits.bitbucket_allowed_repos),
    genericLimits,
  };
}

export function draftValueForField(
  draft: ConnectorDraft,
  fieldName: string,
): string {
  if (fieldName === "jira_allowed_projects") return draft.jiraProjects;
  if (fieldName === "confluence_allowed_spaces") {
    return draft.confluenceSpaces;
  }
  if (fieldName === "confluence_allowed_pages") return draft.confluencePages;
  if (fieldName === "bitbucket_allowed_repos") return draft.bitbucketRepos;
  return draft.genericLimits[fieldName] || "";
}

export function buildLimits(
  draft: ConnectorDraft,
  limitFields: string[],
): Record<string, unknown> {
  const limits: Record<string, unknown> = {};
  for (const fieldName of limitFields) {
    const value = draftValueForField(draft, fieldName);
    if (fieldName === "confluence_allowed_pages") {
      const pages = mergePages(value.trim() ? parsePages(value) : [], draft.confluencePageEntries ?? []);
      if (pages.length) limits[fieldName] = pages;
      continue;
    }
    if (!value.trim()) continue;
    limits[fieldName] = parseLimitField(fieldName, value);
  }
  return limits;
}

/** The typed page lines over the stored entries: a stored entry of a listed id keeps its subtree and excludes,
 * whole-space entries (never shown as a line) are kept as stored. */
function mergePages(
  typed: Array<Record<string, unknown>>,
  stored: Array<Record<string, unknown>>,
): Array<Record<string, unknown>> {
  const merged = typed.map((line) => {
    const own = stored.find((entry) => entry.whole_space !== true && String(entry.id ?? "").trim() === line.id);
    return own ? { ...own, title: line.title || own.title, space_key: line.space_key || own.space_key } : line;
  });
  return [...merged, ...stored.filter((entry) => entry.whole_space === true)];
}

/** The Workspace's page entries as the page picker reads them: the typed lines over the stored entries. */
export function draftPageEntries(draft: ConnectorDraft): Array<Record<string, unknown>> {
  const typed = draft.confluencePages.trim() ? parsePages(draft.confluencePages) : [];
  return mergePages(typed, draft.confluencePageEntries ?? []);
}

/** The draft patch of entries the page picker applied: the lines it can show, and every entry kept for the save. */
export function pageEntriesPatch(entries: Array<Record<string, unknown>>): Partial<ConnectorDraft> {
  return { confluencePages: stringifyPages(entries), confluencePageEntries: entries };
}

/** The spaces the Workspace's page list covers by default: its own allowed spaces, else the inherited ones. */
export function workspaceAllowedSpaces(draft: ConnectorDraft, access: ProjectConnectorAccess): string[] {
  const own = splitLines(draft.confluenceSpaces);
  return own.length ? own : splitLines(stringifySpaces(access.inherited_limits?.confluence_allowed_spaces));
}

export function hasAnyLimit(
  draft: ConnectorDraft,
  limitFields: string[],
): boolean {
  return limitFields.some((fieldName) =>
    Boolean(draftValueForField(draft, fieldName).trim()),
  );
}

/** U2 (connector status consistency): how many of the connector's limits this Workspace has actually saved. */
export function savedProjectLimitCount(access: ProjectConnectorAccess): number {
  const saved = draftFromAccess(access);
  return (access.limit_fields || []).filter((fieldName) =>
    Boolean(draftValueForField(saved, fieldName).trim()),
  ).length;
}

/** The saved Workspace limits in words (the connector table's Limits column). */
export function workspaceLimitText(count: number): string {
  if (!count) return "No Workspace limits";
  return `${count} Workspace limit${count === 1 ? "" : "s"}`;
}

/** The limits in effect, one line per field in words ("Allowed Confluence spaces: TEAM, DOC17"). */
export function inheritedSummary(access: ProjectConnectorAccess): string {
  const limits = access.effective_limits || {};
  const keys = Object.keys(limits);
  if (!keys.length) return "No platform limit is set.";
  return keys.map((key) => `${labelForLimitField(key)}: ${stringifyLimitField(key, limits[key]).split("\n").filter(Boolean).join(", ") || "none"}`).join("\n");
}

const LIMIT_PRODUCTS: Record<string, string> = {
  aws: "AWS", gcp: "GCP", k8s: "Kubernetes", kubernetes: "Kubernetes", github: "GitHub", gitlab: "GitLab",
  jenkins: "Jenkins", nexus: "Nexus", servicenow: "ServiceNow", jira: "Jira", confluence: "Confluence", bitbucket: "Bitbucket",
};

/** A limit field as a sentence-case label: aws_allowed_services → "Allowed AWS services". */
export function labelForLimitField(fieldName: string): string {
  const match = /^([a-z0-9]+)_allowed_(.+)$/.exec(fieldName);
  if (match) {
    const product = LIMIT_PRODUCTS[match[1]] ?? match[1].charAt(0).toUpperCase() + match[1].slice(1);
    return `Allowed ${product} ${match[2].replace(/_/g, " ")}`;
  }
  const words = fieldName.split("_").filter(Boolean).map((word) => LIMIT_PRODUCTS[word] ?? word);
  const text = words.join(" ");
  return text.charAt(0).toUpperCase() + text.slice(1);
}
