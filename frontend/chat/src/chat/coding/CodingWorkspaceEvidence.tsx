import type { WorkCodingWorkspace } from "../work/workCodingPipelineTypes";

type CodingWorkspaceEvidenceProps = {
  workspaces: WorkCodingWorkspace[];
  compact?: boolean;
  emptyText?: string;
};

export function CodingWorkspaceEvidence({
  workspaces,
  compact = false,
  emptyText = "No coding workspace captured yet.",
}: CodingWorkspaceEvidenceProps) {
  const visible = uniqueWorkspaces(workspaces);
  if (visible.length === 0 && compact) {
    return null;
  }
  return (
    <section className="coding-workspace-evidence">
      <div className="coding-workspace-evidence__header">
        <div>
          <div className="work-area__eyebrow">Workspace evidence</div>
          <h3>Coding workspace</h3>
        </div>
        <span className="work-badge">{visible.length} {visible.length === 1 ? "workspace" : "workspaces"}</span>
      </div>
      {visible.length === 0 ? <p className="work-detail__empty">{emptyText}</p> : null}
      {visible.length > 0 ? (
        <div className="coding-workspace-evidence__table" role="table" aria-label="Coding workspace evidence">
          <div className="coding-workspace-evidence__row coding-workspace-evidence__row--head" role="row">
            <span role="columnheader">Repository</span>
            <span role="columnheader">Base</span>
            <span role="columnheader">Branch</span>
            <span role="columnheader">Workspace</span>
            <span role="columnheader">Status</span>
          </div>
          {visible.map((workspace) => (
            <WorkspaceRow key={workspace.id} workspace={workspace} compact={compact} />
          ))}
        </div>
      ) : null}
    </section>
  );
}

function WorkspaceRow({ workspace, compact }: { workspace: WorkCodingWorkspace; compact: boolean }) {
  const repositoryLabel = workspace.repository_name || workspace.repository_slug || workspace.repository_url || "-";
  const base = workspace.resolved_base_branch || workspace.base_branch || "-";
  const featureBranch = workspace.feature_branch || "-";
  const baseCommit = shortCommit(workspace.base_commit);
  const branchUrl = branchBrowseUrl(workspace.repository_url, workspace.feature_branch);
  return (
    <div className="coding-workspace-evidence__row" role="row">
      <span role="cell">
        <ExternalEvidenceLink href={workspace.repository_url} label={repositoryLabel} />
        <small>{[workspace.provider_instance || workspace.provider, workspace.project_key].filter(Boolean).join(" · ")}</small>
      </span>
      <span role="cell">
        {base}
        {baseCommit ? <small>{baseCommit}</small> : null}
      </span>
      <span role="cell">
        <ExternalEvidenceLink href={branchUrl} label={featureBranch} />
      </span>
      <span role="cell">
        <code>{workspace.workspace_path || workspace.source_repository_root || "-"}</code>
        {!compact && workspace.source_repository_root ? <small>{workspace.source_repository_root}</small> : null}
      </span>
      <span role="cell">
        <span className={`work-badge work-badge--${workspaceTone(workspace.status)}`}>{workspace.status || "unknown"}</span>
      </span>
    </div>
  );
}

function uniqueWorkspaces(workspaces: WorkCodingWorkspace[]): WorkCodingWorkspace[] {
  const seen = new Set<string>();
  const rows: WorkCodingWorkspace[] = [];
  for (const workspace of workspaces) {
    const key = workspace.id || `${workspace.repository_slug || workspace.repository_name}:${workspace.feature_branch}`;
    if (!key || seen.has(key)) continue;
    seen.add(key);
    rows.push(workspace);
  }
  return rows;
}

function ExternalEvidenceLink({ href, label }: { href?: string | null; label: string }) {
  if (!href || !isHttpUrl(href)) {
    return <strong>{label}</strong>;
  }
  return (
    <a className="coding-external-link" href={href} target="_blank" rel="noreferrer">
      {label}
    </a>
  );
}

function branchBrowseUrl(repositoryUrl?: string | null, branchName?: string | null): string | null {
  const branch = String(branchName || "").trim();
  const rawUrl = String(repositoryUrl || "").trim();
  if (!branch || !isHttpUrl(rawUrl)) return null;
  const browseUrl = rawUrl.includes("/browse") ? rawUrl : `${rawUrl.replace(/\/$/, "")}/browse`;
  const separator = browseUrl.includes("?") ? "&" : "?";
  return `${browseUrl}${separator}at=${encodeURIComponent(`refs/heads/${branch}`)}`;
}

function shortCommit(value?: string | null): string {
  const text = String(value || "").trim();
  return text ? text.slice(0, 12) : "";
}

function workspaceTone(status?: string | null): "active" | "attention" | "danger" | "neutral" {
  const normalized = String(status || "").toLowerCase();
  if (["prepared", "ready", "active"].includes(normalized)) return "active";
  if (["prepared_empty", "pending", "needs_checkout"].includes(normalized)) return "attention";
  if (["blocked", "failed", "error"].includes(normalized)) return "danger";
  return "neutral";
}

function isHttpUrl(value: string): boolean {
  return /^https?:\/\//i.test(value);
}
