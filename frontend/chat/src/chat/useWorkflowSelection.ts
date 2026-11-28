import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import type { SelectedSession } from "../chatThreadTypes";
import type { WorkflowOption } from "../chatOptionTypes";
import type { WorkflowProposalView } from "../chatDecisionTypes";
import { useWorkflowCatalog } from "./useWorkflowCatalog";
import {
  AUTOMATIC_LABEL,
  automaticWorkflowChip,
  workflowChipText,
} from "./composer/automaticWorkflow";
import {
  beginThreadSwitch as beginSwitch,
  IDLE_THREAD_SWITCH,
  type ThreadSwitchState,
} from "./threadSwitchSelection";
import {
  chooseWorkflowKey,
  followBootstrapMirror,
  readDraftSelection,
  restoreSessionSelection,
} from "./workflowSelectionStore";

export const AUTOMATIC_WORKFLOW_LABEL = AUTOMATIC_LABEL;
export const NO_WORKFLOW_KEY = "none";
export const NO_WORKFLOW_LABEL = "No workflow";

const NO_WORKFLOW_OPTION: WorkflowOption = {
  key: NO_WORKFLOW_KEY,
  title: NO_WORKFLOW_LABEL,
  description: "Continue as a plain chat without a workflow.",
  capability: "",
  workflow_id: "",
  workflow_class: "",
  project_id: null,
  source: "definition",
  selection: "no_workflow",
};

export function workflowProposalPillLabel(
  proposal: WorkflowProposalView | null | undefined,
): string {
  return workflowChipText(automaticWorkflowChip({ proposal }));
}

// No selection is an explicit state, never an empty label.
function workflowPillText(
  selectedWorkflow: WorkflowOption | null,
  selectedWorkflowKey: string,
  workflowProposalEnabled: boolean,
  selectedSession: SelectedSession | null,
) {
  return workflowChipText(
    automaticWorkflowChip({
      selectedWorkflowTitle: selectedWorkflow?.title ?? (selectedWorkflowKey
        ? `${selectedWorkflowKey} · unavailable in this Workspace`
        : null),
      proposal: workflowProposalEnabled ? selectedSession?.workflowProposal : null,
    }),
  );
}

function useThreadWorkflowKey(selectedSession: SelectedSession | null) {
  const [selectedWorkflowKey, setSelectedWorkflowKeyState] = useState(() =>
    readDraftSelection(),
  );
  // null sentinel: the restore effect has not run yet, so it also fires for the session selected at mount.
  const previousSessionIdRef = useRef<string | null>(null);
  // A pick made while a thread switch loads belongs to the new thread.
  const threadSwitchRef = useRef<ThreadSwitchState>(IDLE_THREAD_SWITCH);
  const bootstrapSessionIdRef = useRef<string | null>(null);

  // The server mirrors the last sent selection into session metadata, so a switch restores it on every device.
  const sessionId = selectedSession?.id ?? "";
  const sessionIdRef = useRef(sessionId);
  sessionIdRef.current = sessionId;
  const bootstrapWorkflowKey = selectedSession?.workflowKey;
  useEffect(() => {
    restoreSessionSelection({
      sessionId,
      previousSessionIdRef,
      threadSwitchRef,
      selectedWorkflowKey,
      bootstrapWorkflowKey,
      setSelectedWorkflowKeyState,
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessionId]);

  useEffect(() => {
    followBootstrapMirror(bootstrapSessionIdRef, sessionId, bootstrapWorkflowKey, setSelectedWorkflowKeyState);
  }, [bootstrapWorkflowKey, sessionId]);

  const setSelectedWorkflowKey = (workflowKey: string) =>
    chooseWorkflowKey(threadSwitchRef, sessionId, workflowKey, setSelectedWorkflowKeyState);

  const beginThreadSwitch = useCallback((targetSessionId: string) => {
    threadSwitchRef.current = beginSwitch(sessionIdRef.current, targetSessionId);
  }, []);

  return { selectedWorkflowKey, setSelectedWorkflowKey, beginThreadSwitch };
}

export function useWorkflowSelection({
  selectedSession,
  workspaceId,
}: {
  selectedSession: SelectedSession | null;
  workspaceId: string;
}) {
  const catalog = useWorkflowCatalog(workspaceId);
  const workflowProposalEnabled = catalog.proposalsEnabled;
  const workflowOptions = useMemo(() => [
    ...catalog.options,
    ...(workflowProposalEnabled ? [NO_WORKFLOW_OPTION] : []),
  ], [catalog.options, workflowProposalEnabled]);
  const { selectedWorkflowKey, setSelectedWorkflowKey, beginThreadSwitch } =
    useThreadWorkflowKey(selectedSession);

  const selectedWorkflow = useMemo(
    () =>
      workflowOptions.find((option) => option.key === selectedWorkflowKey) ??
      null,
    [workflowOptions, selectedWorkflowKey],
  );
  const workflowPillLabel = workflowPillText(
    selectedWorkflow,
    selectedWorkflowKey,
    workflowProposalEnabled,
    selectedSession,
  );
  const activeWorkflowChipLabel = `Workflow · ${workflowPillLabel}`;

  return {
    workflowOptions,
    workflowProposalEnabled,
    selectedWorkflowKey,
    setSelectedWorkflowKey,
    beginThreadSwitch,
    selectedWorkflow,
    selectedWorkflowCapability: selectedWorkflow?.capability ?? "",
    workflowPillLabel,
    activeWorkflowChipLabel,
  };
}
