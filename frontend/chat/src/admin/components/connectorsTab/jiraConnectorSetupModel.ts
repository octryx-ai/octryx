import type { AdminConnector } from "../../types/adminPanelTypes.usersProviders";
import { atlassianAuthSaveFields } from "./atlassianAuthModel";
import { atlassianAuthView, atlassianUrlProblem } from "./atlassianAuthView";
import type { AtlassianAuthView, AuthFieldError } from "./atlassianAuthView";

// Guided Jira connector setup (sign-in). The URL and sign-in come from the shared
// Atlassian model (atlassianAuthModel.ts): Atlassian Cloud, or an own Server/Data Center instance with
// a username and password or a personal access token, stored as `jira_auth_mode`. This model adds the
// explicit project scope. The guided choices that are not fields live in the connector draft under
// `__jira_*` keys; the save body only ever contains preset fields and the unchanged policy fields.

export type JiraScope = "restricted" | "all";

export const JIRA_DRAFT_SCOPE = "__jira_scope";
export const JIRA_DRAFT_CONFIRM_ALL = "__jira_confirm_all_projects";
export const JIRA_PROJECTS_FIELD = "jira_allowed_projects";

const PROJECT_KEY = /^[A-Z][A-Z0-9_]*$/;

export type JiraFieldError = AuthFieldError;

export type JiraProjectsInput = { keys: string[]; invalid: string[] };

export type JiraSetupView = {
  auth: AtlassianAuthView;
  storedProjects: string[] | null;
  scope: JiraScope;
  projects: JiraProjectsInput;
  // Moving a stored restriction to all projects.
  broadening: boolean;
  urlNote: string | null;
  errors: Record<string, JiraFieldError>;
};

function draftText(draft: Record<string, string>, field: string): string {
  return String(draft[field] ?? "").trim();
}

// The stored allowlist as the runtime reads it: a non-empty list of keys, else null (no restriction).
export function storedJiraProjects(connector: AdminConnector): string[] | null {
  const raw = connector.public_fields?.[JIRA_PROJECTS_FIELD];
  const items = Array.isArray(raw) ? raw : typeof raw === "string" ? raw.replace(/,/g, " ").split(/\s+/) : [];
  const keys = items.map((item) => String(item).trim().toUpperCase()).filter(Boolean);
  return keys.length ? Array.from(new Set(keys)) : null;
}

function entriesOf(text: string): string[] {
  const trimmed = text.trim();
  if (trimmed.startsWith("[")) {
    try {
      const parsed = JSON.parse(trimmed);
      if (Array.isArray(parsed)) return parsed.map((item) => String(item));
    } catch {
      // Not JSON: read it as a plain list below.
    }
  }
  return trimmed.split(/[\s,;]+/);
}

// One project key per line (commas also separate). Case is normalized and duplicates dropped; an
// invalid entry is reported as typed and stays in the text, it is never silently discarded.
export function parseJiraProjects(text: string): JiraProjectsInput {
  const keys: string[] = [];
  const invalid: string[] = [];
  for (const entry of entriesOf(text)) {
    const value = entry.trim();
    if (!value) continue;
    const key = value.toUpperCase();
    if (!PROJECT_KEY.test(key)) {
      if (!invalid.includes(value)) invalid.push(value);
    } else if (!keys.includes(key)) {
      keys.push(key);
    }
  }
  return { keys, invalid };
}

// The textarea shows one key per line, also for a stored list that arrives as JSON.
export function projectsDisplayText(value: string | undefined): string {
  const trimmed = String(value ?? "").trim();
  if (trimmed.startsWith("[")) {
    try {
      const parsed = JSON.parse(trimmed);
      if (Array.isArray(parsed)) return parsed.map((item) => String(item)).join("\n");
    } catch {
      // Keep what was typed.
    }
  }
  return String(value ?? "");
}

export function jiraUrlProblem(value: string): string | null {
  return atlassianUrlProblem("jira", value);
}

function chosenScope(connector: AdminConnector, draft: Record<string, string>, storedProjects: string[] | null): JiraScope {
  const value = draftText(draft, JIRA_DRAFT_SCOPE);
  if (value === "restricted" || value === "all") return value;
  if (storedProjects) return "restricted";
  // An existing setup without a list is unrestricted and is shown as such; a new one starts restricted.
  return connector.configured ? "all" : "restricted";
}

export function jiraSetupView(connector: AdminConnector, draft: Record<string, string>): JiraSetupView {
  const auth = atlassianAuthView("jira", connector, draft);
  const storedProjects = storedJiraProjects(connector);
  const scope = chosenScope(connector, draft, storedProjects);
  const projects = parseJiraProjects(String(draft[JIRA_PROJECTS_FIELD] ?? ""));
  const broadening = scope === "all" && Boolean(storedProjects);
  const errors: Record<string, JiraFieldError> = { ...auth.errors };

  if (scope === "restricted") {
    if (projects.invalid.length) {
      errors[JIRA_PROJECTS_FIELD] = {
        message: `Not valid Jira project keys: ${projects.invalid.join(", ")}. A key starts with a letter and uses letters, digits or _.`,
        live: true,
      };
    } else if (!projects.keys.length) {
      errors[JIRA_PROJECTS_FIELD] = { message: "Add at least one project key, or choose all projects.", live: false };
    }
  } else if (broadening && draftText(draft, JIRA_DRAFT_CONFIRM_ALL) !== "true") {
    errors[JIRA_DRAFT_CONFIRM_ALL] = {
      message: "Confirm that every project this account can access becomes reachable for the agents.",
      live: true,
    };
  }

  return { auth, storedProjects, scope, projects, broadening, urlNote: auth.urlNote, errors };
}

export function jiraSetupHasErrors(view: JiraSetupView): boolean {
  return Object.keys(view.errors).length > 0;
}

// The Jira part of the save body. Only for a valid view; it never sends `[]`, never sends a secret
// that was not typed, and broadens the scope only after the explicit confirmation.
export function jiraSaveFields(connector: AdminConnector, draft: Record<string, string>): Record<string, unknown> {
  const view = jiraSetupView(connector, draft);
  const body: Record<string, unknown> = atlassianAuthSaveFields("jira", connector, draft);
  if (view.scope === "restricted") {
    if (view.projects.keys.length && !view.projects.invalid.length) body[JIRA_PROJECTS_FIELD] = view.projects.keys;
  } else if (view.broadening && draftText(draft, JIRA_DRAFT_CONFIRM_ALL) === "true") {
    body[JIRA_PROJECTS_FIELD] = "";
  }
  return body;
}
