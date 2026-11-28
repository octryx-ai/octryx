import type { ProjectOption } from "../../../chatOptionTypes";
import { useActiveWorkspace } from "../../../chat/useActiveWorkspace";
import { KnowledgeConnectorsPanel } from "./KnowledgeConnectorsPanel";

export function AdminWorkspaceKnowledgeTab({ projects, isAdmin = false }: { projects: ProjectOption[]; isAdmin?: boolean }) {
  const [workspaceId] = useActiveWorkspace(projects);

  return (
    // A shrinkable column keeps wide content inside the panel.
    <div className="admin-users" style={{ gridTemplateColumns: "minmax(0, 1fr)" }}>
      {!workspaceId ? (
        <div className="admin-panel__empty-state">
          {projects.length ? "Select a workspace to see its sources." : "Create a workspace first."}
        </div>
      ) : (
        <div className="admin-panel__stack">
          <KnowledgeConnectorsPanel key={workspaceId} workspaceId={workspaceId} isPlatformAdmin={isAdmin} />
        </div>
      )}
    </div>
  );
}
