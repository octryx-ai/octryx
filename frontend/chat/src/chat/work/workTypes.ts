

export type WorkNavKey =
  | "runs"
  | "epics"
  | "board"
  | "changePlans"
  | "intake"
  | "writeback";

export type WorkFilters = {
  search: string;
  // "jira" or "servicenow" (empty: every source).
  sourceType: string;
  sourceProject: string;
  sourceStatuses: string[];
  workState: string;
  syncState: string;
  assignees: string[];
  labels: string[];
  automationMode: string;
  fixVersions: string[];
  sprints: string[];
};
