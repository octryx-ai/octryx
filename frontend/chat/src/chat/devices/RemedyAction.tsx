import { createContext, useContext, useEffect, useState } from "react";

import { applyDeviceRunsRemedy, loadDeviceRunsPolicy } from "./devicesApi";
import { REMEDY_BUTTON, remedyBody, remedyChangeText, remedyDoneText, remedyErrorText, type Remedy } from "./remedyModel";
import "./devices.css";

// "Allow in this Workspace" under a refused tool call that names its one-click fix (`remedy`, allow
// by default, blocking is an admin option). Only for people who can edit the Workspace's device-run settings
// (`can_edit` of GET device-runs); the change is confirmed in place first, naming the setting and the value.

/** The Workspace of the chat or run on screen; the remedy applies there. */
export const RemedyWorkspaceContext = createContext<string | null>(null);

// One `can_edit` lookup per Workspace and page load: refusals are rare, and several may stand in one thread.
const canEditCache = new Map<string, Promise<boolean>>();
function canEditWorkspace(projectId: string): Promise<boolean> {
  let answer = canEditCache.get(projectId);
  if (!answer) {
    answer = loadDeviceRunsPolicy(projectId)
      .then((payload) => (payload as { can_edit?: unknown } | null)?.can_edit === true)
      .catch(() => false);
    canEditCache.set(projectId, answer);
  }
  return answer;
}

type Phase = { kind: "idle" } | { kind: "confirm" } | { kind: "busy" } | { kind: "done"; text: string }
  | { kind: "error"; text: string };

export function RemedyAction({ remedy }: { remedy: Remedy }) {
  const projectId = useContext(RemedyWorkspaceContext);
  const [canEdit, setCanEdit] = useState(false);
  const [phase, setPhase] = useState<Phase>({ kind: "idle" });

  useEffect(() => {
    let current = true;
    setCanEdit(false);
    if (projectId) void canEditWorkspace(projectId).then((allowed) => { if (current) setCanEdit(allowed); });
    return () => { current = false; };
  }, [projectId]);

  if (!projectId || !canEdit) return null;
  const apply = async () => {
    setPhase({ kind: "busy" });
    try {
      await applyDeviceRunsRemedy(projectId, remedyBody(remedy));
      setPhase({ kind: "done", text: remedyDoneText(remedy) });
    } catch (error) {
      setPhase({ kind: "error", text: remedyErrorText(error) });
    }
  };

  if (phase.kind === "done") {
    return <p className="remedy__result" role="status" data-testid="remedy-done">{phase.text}</p>;
  }
  if (phase.kind === "confirm" || phase.kind === "busy") {
    return (
      <div className="remedy__confirm" role="group" aria-label={REMEDY_BUTTON} data-testid="remedy-confirm">
        <p className="remedy__text">{remedyChangeText(remedy)} Every member's runs and sessions in this Workspace follow it.</p>
        <div className="device-row">
          <button type="button" className="admin-panel__action-btn" disabled={phase.kind === "busy"}
            onClick={() => setPhase({ kind: "idle" })}>Cancel</button>
          <button type="button" className="admin-panel__action-btn admin-panel__action-btn--primary"
            disabled={phase.kind === "busy"} data-testid="remedy-apply" onClick={() => void apply()}>
            {phase.kind === "busy" ? "Allowing…" : "Allow"}
          </button>
        </div>
      </div>
    );
  }
  return (
    <div className="remedy">
      <button type="button" className="admin-panel__action-btn" data-testid="remedy-button"
        onClick={() => setPhase({ kind: "confirm" })}>{REMEDY_BUTTON}</button>
      {phase.kind === "error" ? <p className="remedy__error" role="alert" data-testid="remedy-error">{phase.text}</p> : null}
    </div>
  );
}
