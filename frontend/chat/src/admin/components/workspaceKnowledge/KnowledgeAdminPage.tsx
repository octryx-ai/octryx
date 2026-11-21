import type { ProjectOption } from "../../../chatOptionTypes";
import { useActiveWorkspace } from "../../../chat/useActiveWorkspace";
import { KnowledgeBindingsPanel } from "./KnowledgeBindingsPanel";
import { KnowledgeChangesPanel } from "./KnowledgeChangesPanel";
import { KnowledgeEpisodePolicyPanel } from "./KnowledgeEpisodePolicyPanel";
import { KnowledgeMemoryPanel } from "./KnowledgeMemoryPanel";
import { KnowledgePackagesPanel } from "./KnowledgePackagesPanel";
import { StructuredGraphPanel } from "./StructuredGraphPanel";
import { StructuredProfilePanel } from "./StructuredProfilePanel";

// Admin › Knowledge: the Workspace knowledge pages, one page each, with the shared Workspace switch and
// server-side authorization.
export type KnowledgeAdminTab =
  | "knowledgePackages" | "knowledgeBindings" | "knowledgeChanges" | "knowledgeHandbook" | "knowledgeMemory"
  | "knowledgeEpisodes";

function Section({ tab, workspaceId, projects }: { tab: KnowledgeAdminTab; workspaceId: string; projects: ProjectOption[] }) {
  switch (tab) {
    case "knowledgePackages":
      return <KnowledgePackagesPanel workspaceId={workspaceId} />;
    case "knowledgeBindings":
      return <KnowledgeBindingsPanel workspaceId={workspaceId} projects={projects} />;
    case "knowledgeChanges":
      return <KnowledgeChangesPanel workspaceId={workspaceId} />;
    case "knowledgeHandbook":
      return (
        <div className="admin-panel__stack">
          <StructuredGraphPanel workspaceId={workspaceId} />
          <StructuredProfilePanel workspaceId={workspaceId} />
        </div>
      );
    case "knowledgeMemory":
      return <KnowledgeMemoryPanel workspaceId={workspaceId} />;
    case "knowledgeEpisodes":
      return <KnowledgeEpisodePolicyPanel workspaceId={workspaceId} />;
  }
}

export function KnowledgeAdminPage({ tab, projects }: { tab: KnowledgeAdminTab; projects: ProjectOption[] }) {
  const [workspaceId] = useActiveWorkspace(projects);
  return (
    <div className="admin-users" style={{ gridTemplateColumns: "minmax(0, 1fr)" }}>
      {workspaceId ? (
        <Section key={`${tab}:${workspaceId}`} tab={tab} workspaceId={workspaceId} projects={projects} />
      ) : (
        <div className="admin-panel__empty-state">
          {projects.length ? "Select a workspace to manage its knowledge." : "Create a workspace first."}
        </div>
      )}
    </div>
  );
}
