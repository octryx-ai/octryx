// GitHub repositories of the GitHub connector: list them and create a new one.
import type { GitHubConnectorRepository } from "../types/adminPanelTypes.usersProviders";
import type { UseAdminConnectorManagementArgs } from "./useAdminConnectorManagement.types";

type GithubRepositoryDeps = Pick<
  UseAdminConnectorManagementArgs,
  | "readJson"
  | "setGithubConnectorRepositories"
  | "setGithubConnectorRepositoriesLoading"
  | "setGithubConnectorRepoCreateLoading"
  | "setGithubConnectorRepoError"
  | "githubConnectorRepoForm"
  | "setGithubConnectorRepoForm"
>;

export function githubConnectorRepositoryActions({
  readJson,
  setGithubConnectorRepositories,
  setGithubConnectorRepositoriesLoading,
  setGithubConnectorRepoCreateLoading,
  setGithubConnectorRepoError,
  githubConnectorRepoForm,
  setGithubConnectorRepoForm,
}: GithubRepositoryDeps) {
  const handleLoadGithubConnectorRepositories = async () => {
    setGithubConnectorRepositoriesLoading(true);
    setGithubConnectorRepoError(null);
    try {
      const payload = await readJson<{ items: GitHubConnectorRepository[] }>(
        "/admin/chat/api/panel/connectors/github/repositories",
      );
      setGithubConnectorRepositories(payload.items || []);
    } catch (err) {
      setGithubConnectorRepoError(
        err instanceof Error
          ? err.message
          : "Failed to load GitHub repositories",
      );
    } finally {
      setGithubConnectorRepositoriesLoading(false);
    }
  };

  const handleCreateGithubConnectorRepository = async () => {
    setGithubConnectorRepoCreateLoading(true);
    setGithubConnectorRepoError(null);
    try {
      await readJson("/admin/chat/api/panel/connectors/github/repositories", {
        method: "POST",
        body: JSON.stringify({
          ...githubConnectorRepoForm,
          owner: githubConnectorRepoForm.owner.trim() || undefined,
          local_path: githubConnectorRepoForm.local_path.trim() || undefined,
          project_id:
            githubConnectorRepoForm.register_code_repository &&
            githubConnectorRepoForm.project_id
              ? githubConnectorRepoForm.project_id
              : undefined,
        }),
      });
      setGithubConnectorRepoForm((prev) => ({
        ...prev,
        name: "",
        description: "",
        local_path: "",
      }));
      await handleLoadGithubConnectorRepositories();
    } catch (err) {
      setGithubConnectorRepoError(
        err instanceof Error
          ? err.message
          : "Failed to create GitHub repository",
      );
    } finally {
      setGithubConnectorRepoCreateLoading(false);
    }
  };

  return { handleLoadGithubConnectorRepositories, handleCreateGithubConnectorRepository };
}
