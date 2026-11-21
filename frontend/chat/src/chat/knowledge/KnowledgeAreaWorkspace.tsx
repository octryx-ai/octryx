import type { ProjectOption } from "../../chatOptionTypes";
import { KnowledgeSearchPanel } from "../../admin/components/workspaceKnowledge/KnowledgeSearchPanel";
import { useActiveWorkspace } from "../useActiveWorkspace";
import { ChooseWorkspaceLine } from "../workspace/ChooseWorkspaceLine";
import { KnowledgeSourceInventory } from "./KnowledgeSourceInventory";
import { KnowledgeResearchSourcesPanel } from "./KnowledgeResearchSourcesPanel";
import { KnowledgeExplorePage } from "./explore/KnowledgeExplorePage";
import { useKnowledgePermissions } from "./useKnowledgePermissions";
import "./knowledge-workspace.css";

export type KnowledgePageView = "library" | "sources" | "research" | "relationships" | "graph";

function KnowledgeView({ workspaceId, view, projects, isAdmin, onWorkspaceChange }: {
  workspaceId: string;
  view: KnowledgePageView;
  projects: ProjectOption[];
  isAdmin: boolean;
  onWorkspaceChange: (workspaceId: string) => void;
}) {
  const mayAuthor = useKnowledgePermissions(workspaceId);
  if (view === "sources") return <KnowledgeSourceInventory workspaceId={workspaceId} mayAuthor={mayAuthor} />;
  if (view === "research") return <KnowledgeResearchSourcesPanel workspaceId={workspaceId} mayAuthor={mayAuthor} />;
  // Relationships and Graph are the List and Graph views of Explore.
  if (view === "relationships" || view === "graph") {
    return <KnowledgeExplorePage workspaceId={workspaceId} view={view === "graph" ? "graph" : "list"} isAdmin={isAdmin}
      projects={projects} onWorkspaceChange={onWorkspaceChange} />;
  }
  return <KnowledgeSearchPanel workspaceId={workspaceId} isAdmin={isAdmin} />;
}

// One Knowledge page inside the shared area shell. Permissions remain
// server-owned; every operation uses the existing workspace-scoped API.
export function KnowledgeAreaPage({ projects, view, isAdmin = false }: {
  projects: ProjectOption[]; view: KnowledgePageView; isAdmin?: boolean;
}) {
  const [workspaceId, setWorkspaceId] = useActiveWorkspace(projects);
  const workspace = projects.find((project) => project.id === workspaceId);

  return (
    <div className="knowledge-workspace__page">
      {/* The Workspace comes from the one global switch at the head of the rail. */}
      {workspace ? (
        <section key={workspace.id} aria-label={`Knowledge in ${workspace.name}`}>
          {/* Both Explore views share one key, so the filter and the selected entity stay across a view switch. */}
          <KnowledgeView key={`${workspace.id}-${view === "graph" ? "relationships" : view}`} workspaceId={workspace.id}
            view={view} projects={projects} isAdmin={isAdmin} onWorkspaceChange={setWorkspaceId} />
        </section>
      ) : (
        <ChooseWorkspaceLine projects={projects} purpose="to search or manage its knowledge" />
      )}
    </div>
  );
}
