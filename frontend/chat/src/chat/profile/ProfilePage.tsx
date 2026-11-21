import { PageHeader } from "../../layout/PageHeader";
import type { ProjectOption } from "../../chatOptionTypes";
import { PersonalEngineCard } from "../engines/EngineCards";
import { useActiveWorkspace } from "../useActiveWorkspace";
import { LinkedAccountsPanel } from "./LinkedAccountsPanel";

// My settings → Profile: the signed-in user's linked external accounts (self-service) and their coding engine
// (Claude Code or Codex) in the Workspace in focus.
export function ProfilePage({ projects = [], fallbackWorkspaceId = null }: {
  projects?: ProjectOption[];
  fallbackWorkspaceId?: string | null;
}) {
  const [workspaceId] = useActiveWorkspace(projects, fallbackWorkspaceId);
  const workspaceName = projects.find((project) => project.id === workspaceId)?.name ?? "";
  return (
    <>
      <div className="admin-panel__header">
        <PageHeader eyebrow="My settings" title="Profile"
          purpose="Your accounts in other systems, so pull requests and work items count as yours, and the coding engine your sessions run on." />
      </div>
      <div className="admin-panel__body">
        <div className="admin-panel__stack">
          <LinkedAccountsPanel userId="me" ownAccounts />
          <PersonalEngineCard projectId={workspaceId} workspaceName={workspaceName} />
        </div>
      </div>
    </>
  );
}
