import { ConfiguredConnectorGithubRepoForm } from "./ConfiguredConnectorGithubRepoForm";

type ConfiguredConnectorGithubPanelProps = {
  connector: any;
  ctx: Record<string, unknown>;
};

export function ConfiguredConnectorGithubPanel({
  connector,
  ctx,
}: ConfiguredConnectorGithubPanelProps) {
  const {
    githubConnectorRepoError,
    githubConnectorRepositories,
    githubConnectorRepositoriesLoading,
    handleLoadGithubConnectorRepositories,
  } = ctx as Record<string, any>;

  return (
    <div className="connector-card__tools">
      <div className="connector-card__tools-label">Managed repositories</div>
      <div className="admin-inline-actions" style={{ marginBottom: 10 }}>
        <button
          type="button"
          className="admin-panel__action-btn"
          disabled={!connector.configured || githubConnectorRepositoriesLoading}
          onClick={() => void handleLoadGithubConnectorRepositories()}
        >
          {githubConnectorRepositoriesLoading
            ? "Loading…"
            : "Load repositories"}
        </button>
      </div>

      {githubConnectorRepoError ? (
        <div className="connector-card__test-result connector-card__test-result--fail">
          {githubConnectorRepoError}
        </div>
      ) : null}

      {githubConnectorRepositories.length === 0 ? (
        <div className="connector-card__health-empty">
          No GitHub repositories loaded yet.
        </div>
      ) : (
        <div
          className="connector-card__tools-list"
          style={{ marginBottom: 12 }}
        >
          <div className="connector-card__health-empty">
            Loaded {githubConnectorRepositories.length} repositories.
          </div>
          {githubConnectorRepositories.map((repo: any) => (
            <div key={repo.full_name} className="connector-tool">
              <span className="connector-tool__name">{repo.full_name}</span>
              <span className="connector-tool__desc">
                {repo.private ? "private" : "public"} · {repo.default_branch}
                {repo.html_url ? ` · ${repo.html_url}` : ""}
              </span>
            </div>
          ))}
        </div>
      )}

      <ConfiguredConnectorGithubRepoForm connector={connector} ctx={ctx} />
    </div>
  );
}
