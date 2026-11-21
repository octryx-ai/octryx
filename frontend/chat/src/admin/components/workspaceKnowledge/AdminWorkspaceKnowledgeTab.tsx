import type { ProjectOption } from "../../../chatOptionTypes";
import { useActiveWorkspace } from "../../../chat/useActiveWorkspace";
import { KnowledgeConnectorsPanel } from "./KnowledgeConnectorsPanel";

// Knowledge › Sources (page id `workspaceKnowledge`): the systems Knowledge reads for one Workspace. Whether
// launcher sessions upload local repository snapshots is a Workspace setting (Settings › Workspace › Repositories),
// not a card on this page.
// The workspace is the shared active workspace, so it stays the same across the Knowledge pages.
// isAdmin: presentation only (the server decides): whether the caller is a platform admin.
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
