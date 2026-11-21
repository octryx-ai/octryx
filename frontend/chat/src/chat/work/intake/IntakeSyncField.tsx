import { useEffect, useState } from "react";

import { Field } from "../../../admin/components/restApis/restApisParts";
import { loadWorkflows } from "../workApi";
import { neutralLabel } from "../syncNames";
import { syncChoices, syncModeOfSelect, syncSelectValue } from "./intakeSyncModel";
import { writeBackSync } from "./restIntakeModel";

// The Sync of one intake source (backend), the same for every source type in the How step. `workflowMode` is
// the Workspace workflow's mode as the overview reports it; without one (no intake follows the workflow yet) the
// Workspace's workflows are read here.

export function IntakeSyncField({ mode, workflowMode, workspaceId, error, onChange }: {
  mode: string | null | undefined;
  workflowMode: string | null | undefined;
  workspaceId: string;
  error?: string;
  onChange: (mode: string | null) => void;
}) {
  const [read, setRead] = useState<string | null | undefined>(undefined);
  useEffect(() => {
    if (workflowMode !== undefined || !workspaceId) return;
    let active = true;
    loadWorkflows().then((workflows) => {
      if (!active) return;
      const sync = writeBackSync(workflows, workspaceId);
      setRead(sync.mode === "execute" ? "execute" : sync.mode === "dry_run" ? "dry_run_only" : null);
    }).catch(() => active && setRead(null));
    return () => { active = false; };
  }, [workflowMode, workspaceId]);
  const now = workflowMode !== undefined ? workflowMode : read;
  return (
    <Field label={neutralLabel("sync_mode")} error={error} testId="intake-sync-mode"
      hint="Whether this source's write-backs only preview or also write. A transition without a person is only proposed.">
      <select className="admin-panel__input" value={syncSelectValue(mode)} onChange={(event) => onChange(syncModeOfSelect(event.target.value))}>
        {syncChoices(now).map((choice) => <option key={choice.value} value={choice.value}>{choice.label}</option>)}
      </select>
    </Field>
  );
}
