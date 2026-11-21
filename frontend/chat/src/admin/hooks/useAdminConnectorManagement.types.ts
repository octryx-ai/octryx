import type { Dispatch, SetStateAction } from "react";

import type { AdminConnector, AdminConnectorHealthLog, AdminDatabaseConnector, AdminDatabaseTool, GitHubConnectorRepository } from "../types/adminPanelTypes.usersProviders";

export type ReadJsonFn = <T>(
  input: RequestInfo,
  init?: RequestInit,
) => Promise<T>;

export type ConnectorPolicyDraft = {
  tool_instructions: string;
  extra_tools: string[];
  disabled_tools: string[];
};

export type GitHubConnectorRepoForm = {
  name: string;
  description: string;
  owner: string;
  owner_type: string;
  visibility: string;
  default_branch: string;
  local_path: string;
  create_readme: boolean;
  create_gitignore: boolean;
  initial_commit: boolean;
  register_code_repository: boolean;
  project_id: string;
  index_backend: string;
  semantic_backend: string;
  structure_backend: string;
  graph_backend: string;
};

export type DatabaseConnectorForm = {
  name: string;
  description: string;
  db_type: string;
  host: string;
  port: string;
  database: string;
  username: string;
  password: string;
  dsn: string;
  driver: string;
  file_path: string;
  is_active: boolean;
};

export type DatabaseToolForm = {
  connector_id: string;
  tool_name: string;
  display_name: string;
  description: string;
  sql_template: string;
  parameters_schema: string;
  row_level_security_rules: string;
  allowed_roles: string;
  max_rows: string;
  timeout_seconds: string;
  is_active: boolean;
};

export type DatabaseConnectorDraft = {
  description: string;
  db_type: string;
  host: string;
  port: string;
  database: string;
  username: string;
  password: string;
  dsn: string;
  driver: string;
  file_path: string;
  is_active: boolean;
};

export type UseAdminConnectorManagementArgs = {
  readJson: ReadJsonFn;
  connectors: AdminConnector[];
  setConnectors: Dispatch<SetStateAction<AdminConnector[]>>;
  expandedConnector: string | null;
  setExpandedConnector: Dispatch<SetStateAction<string | null>>;
  connectorDraft: Record<string, Record<string, string>>;
  setConnectorDraft: Dispatch<
    SetStateAction<Record<string, Record<string, string>>>
  >;
  connectorPolicyDraft: Record<string, ConnectorPolicyDraft>;
  setConnectorPolicyDraft: Dispatch<
    SetStateAction<Record<string, ConnectorPolicyDraft>>
  >;
  setConnectorSaving: Dispatch<SetStateAction<string | null>>;
  setConnectorTesting: Dispatch<SetStateAction<string | null>>;
  setConnectorTestResult: Dispatch<
    SetStateAction<
      Record<string, { ok: boolean; summary: string; details?: string }>
    >
  >;
  connectorHealthHistory: Record<string, AdminConnectorHealthLog[]>;
  setConnectorHealthHistory: Dispatch<
    SetStateAction<Record<string, AdminConnectorHealthLog[]>>
  >;
  setConnectorHealthLoading: Dispatch<SetStateAction<string | null>>;
  githubConnectorRepositories: GitHubConnectorRepository[];
  setGithubConnectorRepositories: Dispatch<
    SetStateAction<GitHubConnectorRepository[]>
  >;
  setGithubConnectorRepositoriesLoading: Dispatch<SetStateAction<boolean>>;
  setGithubConnectorRepoCreateLoading: Dispatch<SetStateAction<boolean>>;
  setGithubConnectorRepoError: Dispatch<SetStateAction<string | null>>;
  githubConnectorRepoForm: GitHubConnectorRepoForm;
  setGithubConnectorRepoForm: Dispatch<SetStateAction<GitHubConnectorRepoForm>>;
  databaseConnectorForm: DatabaseConnectorForm;
  setDatabaseConnectorForm: Dispatch<SetStateAction<DatabaseConnectorForm>>;
  databaseToolForm: DatabaseToolForm;
  setDatabaseToolForm: Dispatch<SetStateAction<DatabaseToolForm>>;
  setDatabaseConnectorSaving: Dispatch<SetStateAction<boolean>>;
  setDatabaseToolSaving: Dispatch<SetStateAction<boolean>>;
  setDatabaseConnectorError: Dispatch<SetStateAction<string | null>>;
  setDatabaseToolError: Dispatch<SetStateAction<string | null>>;
  setDatabaseConnectorTestBusy: Dispatch<SetStateAction<string | null>>;
  setDatabaseConnectorTestResult: Dispatch<
    SetStateAction<
      Record<string, { ok: boolean; summary: string; details?: string }>
    >
  >;
  setShowAddDatabaseConnector: Dispatch<SetStateAction<boolean>>;
  setShowAddDatabaseTool: Dispatch<SetStateAction<boolean>>;
  expandedDatabaseConnector: string | null;
  setExpandedDatabaseConnector: Dispatch<SetStateAction<string | null>>;
  databaseConnectorDrafts: Record<string, DatabaseConnectorDraft>;
  setDatabaseConnectorDrafts: Dispatch<
    SetStateAction<Record<string, DatabaseConnectorDraft>>
  >;
  databaseConnectors: AdminDatabaseConnector[];
  setDatabaseConnectors: Dispatch<SetStateAction<AdminDatabaseConnector[]>>;
  setDatabaseTools: Dispatch<SetStateAction<AdminDatabaseTool[]>>;
};
