import { lazy, Suspense } from "react";
import { ChooseWorkspaceLine } from "../workspace/ChooseWorkspaceLine";
import { codingWorkspaceView } from "../workspaceDestinations";
import { useActiveWorkspace } from "../useActiveWorkspace";
import type { ProjectOption } from "../../chatOptionTypes";
import { CodingAreaWorkspace } from "./CodingAreaWorkspace";
import { RepositoryPage } from "./repository/RepositoryPage";
import type { AdminTab } from "../../admin/types/adminPanelTypes.governance";
import "./repository/repositories.css";
import { LoadingState } from "../../layout/LoadingState";

const RepositoryList = lazy(async () => ({ default: (await import("./repository/RepositoryList")).RepositoryList }));

export function CodingWorkspaceEntry({ projects, initialWorkspaceId, canManageWork = false, onOpenAdminTab,
  onOpenArea }: {
  projects: ProjectOption[]; initialWorkspaceId: string; canManageWork?: boolean; isPlatformAdmin?: boolean;
  onOpenAdminTab?: (tab: AdminTab) => void;
  onOpenArea?: (area: "work", params: Record<string, string>) => void;
}) {
  const [workspaceId] = useActiveWorkspace(projects, initialWorkspaceId);
  const activeView = codingWorkspaceView(canManageWork);
  // The Workspace comes from the one global switch; no switch of its own here.
  const workspaceControl = null;
  // Who manages work sees Repositories as a page of the Work menu; a member sees the repository list alone.
  return <div className="coding-entry">
    {activeView === "work" ? <CodingAreaWorkspace projects={projects} initialWorkspaceId={initialWorkspaceId}
      onOpenAdminTab={onOpenAdminTab} onOpenArea={onOpenArea} /> : workspaceId ? <Suspense fallback={
      <RepositoryPage controls={workspaceControl} busy><LoadingState label="repositories" /></RepositoryPage>
    }>
      <RepositoryList key={workspaceId} workspaceId={workspaceId} workspaceControl={workspaceControl} />
    </Suspense> : <RepositoryPage controls={workspaceControl}>
      <ChooseWorkspaceLine projects={projects} purpose="to see its repositories" />
    </RepositoryPage>}
  </div>;
}
