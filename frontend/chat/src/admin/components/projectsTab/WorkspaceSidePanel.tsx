import { useEffect, useState, type ReactNode } from "react";

import { SidePanel } from "../../../layout/SidePanel";
import { StatusLabel } from "../../../layout/StatusLabel";
import type { AdminProjectQuality } from "../../types/projectQualityTypes";
import { readJson } from "../../utils/adminPanelHelpers";
import { connectorsApi } from "../workspaceKnowledge/connectorsApi";
import { workspaceGlance, type WorkspaceGlance } from "./workspaceGlance";
import { workspaceListRow } from "./workspaceListRow";

// Admin › Workspaces: a row opens the Workspace's essentials in a side panel — default flag, class,
// members and their roles, Knowledge sources, the connections available in it and its problems — read from today's
// endpoints. "Open settings" (the footer's primary action) opens its full settings; Make default, Archive and Delete
// stay in the row's ⋯ menu.

async function loadGlance(workspaceId: string): Promise<WorkspaceGlance> {
  const id = encodeURIComponent(workspaceId);
  const [access, sources, connections] = await Promise.allSettled([
    readJson<Record<string, unknown>>(`/admin/chat/api/panel/projects/${id}/access`),
    connectorsApi.list(workspaceId),
    readJson<{ connections?: unknown }>(`/api/v1/workspaces/${id}/connections`),
  ]);
  const rows = (value: unknown) => (Array.isArray(value) ? value : []);
  return workspaceGlance(
    access.status === "fulfilled" ? access.value : null,
    sources.status === "fulfilled" ? sources.value.connectors ?? [] : null,
    connections.status === "fulfilled" ? rows(connections.value?.connections) : null,
  );
}

function Fact({ label, children, testId }: { label: string; children: ReactNode; testId?: string }) {
  return <dl className="work-detail__kv" data-testid={testId}><dt>{label}</dt><dd>{children}</dd></dl>;
}

export function WorkspaceSidePanel({ project, problems, onClose, onOpenSettings }: {
  project: AdminProjectQuality;
  // Open problems of this Workspace (Admin › Problems); undefined while unknown.
  problems?: { total: number; problem: number } | null;
  onClose: () => void;
  onOpenSettings: () => void;
}) {
  const [glance, setGlance] = useState<WorkspaceGlance | null>(null);
  useEffect(() => {
    let current = true;
    setGlance(null);
    void loadGlance(project.id).then((next) => { if (current) setGlance(next); });
    return () => { current = false; };
  }, [project.id]);

  const row = workspaceListRow(project);
  const subtitle = [project.is_default ? "Default workspace" : "", project.is_system ? "System" : "",
    row.classLabel !== "—" ? row.classLabel : ""].filter(Boolean).join(" · ");
  const problemsHref = `/chat?area=admin&tab=adminProblems&workspace_id=${encodeURIComponent(project.id)}`;

  return (
    <SidePanel
      title={row.name}
      subtitle={subtitle || undefined}
      onClose={onClose}
      testId="workspace-panel"
      headerActions={<StatusLabel label={row.isActive ? "Active" : "Archived"} testId="workspace-panel-state" />}
      footer={(
        <button type="button" className="admin-panel__action-btn admin-panel__action-btn--primary" onClick={onOpenSettings}
          data-testid="workspace-open-settings">Open settings</button>
      )}
    >
      <div className="work-detail__kv-grid" data-testid="workspace-panel-facts">
        <Fact label="Description">{row.descriptionTitle || "—"}</Fact>
        <Fact label="Default">{project.is_default ? "Yes · people start here" : "No"}</Fact>
        <Fact label="Members" testId="workspace-panel-members">{glance ? glance.members : "…"}</Fact>
        <Fact label="Sources" testId="workspace-panel-sources">{glance ? glance.sources : "…"}</Fact>
        <Fact label="Connections" testId="workspace-panel-connections">{glance ? glance.connections : "…"}</Fact>
        <Fact label="Problems" testId="workspace-panel-problems">
          {problems === undefined || problems === null ? "—" : problems.total === 0 ? "None" : (
            <a href={problemsHref}>
              <StatusLabel label={`${problems.total} open`} tone={problems.problem > 0 ? "problem" : "attention"} />
            </a>
          )}
        </Fact>
      </div>
    </SidePanel>
  );
}
