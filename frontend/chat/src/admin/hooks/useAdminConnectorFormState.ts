import { useState } from "react";
import {
  createDefaultDatabaseConnectorForm,
  createDefaultDatabaseToolForm,
  createDefaultGithubConnectorRepoForm,
} from "../config/adminPanelDefaults";
import type { AdminConnectorHealthLog, GitHubConnectorRepository } from "../types/adminPanelTypes.usersProviders";

export function useAdminConnectorFormState() {
  const [githubConnectorRepositories, setGithubConnectorRepositories] =
    useState<GitHubConnectorRepository[]>([]);
  const [
    githubConnectorRepositoriesLoading,
    setGithubConnectorRepositoriesLoading,
  ] = useState(false);
  const [
    githubConnectorRepoCreateLoading,
    setGithubConnectorRepoCreateLoading,
  ] = useState(false);
  const [githubConnectorRepoError, setGithubConnectorRepoError] = useState<
    string | null
  >(null);
  const [githubConnectorRepoForm, setGithubConnectorRepoForm] = useState(() =>
    createDefaultGithubConnectorRepoForm(),
  );
  const [databaseConnectorForm, setDatabaseConnectorForm] = useState(() =>
    createDefaultDatabaseConnectorForm(),
  );
  const [databaseToolForm, setDatabaseToolForm] = useState(() =>
    createDefaultDatabaseToolForm(),
  );
  const [databaseConnectorSaving, setDatabaseConnectorSaving] = useState(false);
  const [databaseToolSaving, setDatabaseToolSaving] = useState(false);
  const [databaseConnectorError, setDatabaseConnectorError] = useState<
    string | null
  >(null);
  const [databaseToolError, setDatabaseToolError] = useState<string | null>(
    null,
  );
  const [databaseConnectorTestBusy, setDatabaseConnectorTestBusy] = useState<
    string | null
  >(null);
  const [databaseConnectorTestResult, setDatabaseConnectorTestResult] =
    useState<
      Record<string, { ok: boolean; summary: string; details?: string }>
    >({});
  const [showAddDatabaseConnector, setShowAddDatabaseConnector] =
    useState(false);
  const [showAddDatabaseTool, setShowAddDatabaseTool] = useState(false);
  const [expandedDatabaseConnector, setExpandedDatabaseConnector] = useState<
    string | null
  >(null);
  const [databaseConnectorDrafts, setDatabaseConnectorDrafts] = useState<
    Record<
      string,
      {
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
      }
    >
  >({});
  const [connectorHealthHistory, setConnectorHealthHistory] = useState<
    Record<string, AdminConnectorHealthLog[]>
  >({});
  const [connectorHealthLoading, setConnectorHealthLoading] = useState<
    string | null
  >(null);

  return {
    connectorHealthHistory,
    setConnectorHealthHistory,
    connectorHealthLoading,
    setConnectorHealthLoading,
    databaseConnectorDrafts,
    setDatabaseConnectorDrafts,
    databaseConnectorError,
    setDatabaseConnectorError,
    databaseConnectorForm,
    setDatabaseConnectorForm,
    databaseConnectorSaving,
    setDatabaseConnectorSaving,
    databaseConnectorTestBusy,
    setDatabaseConnectorTestBusy,
    databaseConnectorTestResult,
    setDatabaseConnectorTestResult,
    databaseToolError,
    setDatabaseToolError,
    databaseToolForm,
    setDatabaseToolForm,
    databaseToolSaving,
    setDatabaseToolSaving,
    expandedDatabaseConnector,
    setExpandedDatabaseConnector,
    githubConnectorRepoCreateLoading,
    setGithubConnectorRepoCreateLoading,
    githubConnectorRepoError,
    setGithubConnectorRepoError,
    githubConnectorRepoForm,
    setGithubConnectorRepoForm,
    githubConnectorRepositories,
    setGithubConnectorRepositories,
    githubConnectorRepositoriesLoading,
    setGithubConnectorRepositoriesLoading,
    showAddDatabaseConnector,
    setShowAddDatabaseConnector,
    showAddDatabaseTool,
    setShowAddDatabaseTool,
  };
}
