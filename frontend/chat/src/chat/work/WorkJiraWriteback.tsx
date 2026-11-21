import { useState } from "react";

import type { ProjectOption } from "../../chatOptionTypes";
import { createWorkWorkflow } from "./workApi";
import type { WorkWorkflowDefinition } from "./workSyncWorkflowTypes";
import { WorkWorkflowList } from "./WorkWorkflowList";
import { DEFAULT_WORKFLOW_PAYLOAD } from "./workWritebackDefaults";

// Work → Configure → Jira write-back: what Work writes back to Jira when an item changes
// state, for the active Workspace (its own write-backs and the ones that apply to every Workspace). Activation and
// the execute-mode switch ask for confirmation.
export function WorkJiraWriteback({ workflows, workspaceId, projects, onChanged }: {
  workflows: WorkWorkflowDefinition[];
  workspaceId: string;
  projects: ProjectOption[];
  onChanged: () => Promise<void>;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const scoped = workflows.filter((workflow) => workflow.project_id === workspaceId || !workflow.project_id);

  async function createStandard() {
    setBusy(true);
    setError(null);
    try {
      await createWorkWorkflow({ ...DEFAULT_WORKFLOW_PAYLOAD, project_id: workspaceId, is_default: false });
      await onChanged();
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : "Could not create the write-back.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="work-intake">
      {scoped.length ? (
        <WorkWorkflowList workflows={scoped} projects={projects} onChanged={onChanged} />
      ) : (
        <div className="admin-panel__empty-state">
          <div>
            <p>No Jira write-back for this Workspace yet. Work items still sync in; nothing is written to Jira.</p>
            <button type="button" className="admin-panel__action-btn" disabled={busy} onClick={() => void createStandard()}>
              Create the standard write-back (dry-run)
            </button>
          </div>
        </div>
      )}
      {error ? <div className="work-area__error" role="alert">{error}</div> : null}
    </div>
  );
}
