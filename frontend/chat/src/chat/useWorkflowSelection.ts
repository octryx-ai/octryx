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

// Explicit workflow selection (S4 of the explicit-workflow-selection plan):
// the composer offers the published workflows from GET /chat/api/workflows;
// the selected key is sent as ChatSendRequest.workflow_key. No selection means
// "Automatic": the platform may propose a published workflow before the
// turn, which waits for the user's start — never a keyword guess. The explicit
// choice sits behind the composer's "Advanced" disclosure; "No workflow"
// (workflow_key "none") is an explicit choice of its own.

// The default is always "Automatic": the platform may propose a
// workflow before the turn.
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

// Chip text while the composer is on "Automatic": the proposal of the
// thread's current turn with its reason, if any, otherwise "Automatic".
export function workflowProposalPillLabel(
  proposal: WorkflowProposalView | null | undefined,
): string {
  return workflowChipText(automaticWorkflowChip({ proposal }));
}

// No selection is an explicit state, never an empty label: the chip reads
// "Automatic", or the suggested workflow of the thread's current turn with its
// reason, or the workflow chosen in Advanced.
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

// The selected workflow key of the shown thread: restored on a thread switch, following the session mirror,
// and kept for the new thread when picked while a switch loads.
function useThreadWorkflowKey(selectedSession: SelectedSession | null) {
  const [selectedWorkflowKey, setSelectedWorkflowKeyState] = useState(() =>
    readDraftSelection(),
  );
  // null sentinel = the restore effect has not run yet, so it also fires for
  // the session that is already selected at mount.
  const previousSessionIdRef = useRef<string | null>(null);
  // A pick made while a thread switch loads belongs to the new thread.
  const threadSwitchRef = useRef<ThreadSwitchState>(IDLE_THREAD_SWITCH);
  const bootstrapSessionIdRef = useRef<string | null>(null);

  // Switching threads restores that thread's selection from the server, which mirrors the last sent selection
  // into session metadata (bootstrap selectedSession.workflowKey; "" = standard), on every device; a selection made
  // on a fresh thread survives the session id being assigned on the first send.
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

  // The owner calls this when the user starts opening another thread ("" = a
  // new thread), before the navigation loads.
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
