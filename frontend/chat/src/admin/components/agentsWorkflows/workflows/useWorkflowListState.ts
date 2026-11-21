// The Workflows list's state: the overview, the search and filters, the open workflow, unsaved-edit guarding and
// the On/Off switch per workflow; plus the address change for starting a new flow.
import { useCallback, useEffect, useState, type Dispatch, type SetStateAction } from "react";

import { useAdminNavigation } from "../../../adminNavigation";
import { NEW_FLOW_PARAM } from "../../../editorLinks";
import type { ReadJsonFn } from "../../../hooks/useAdminTabLoader.types";
import {
  listUrl, readOpenWorkflow, requestLeave, type KindFilter, type ListedWorkflow, type OpenWorkflow, type WorkflowsListView,
} from "./workflowListModel";
import {
  WORKFLOWS_OVERVIEW_PATH, flowActivePath, readWorkflowsOverview, type ScopeFilter, type WorkflowsOverview,
} from "./workflowsModel";

// On/Off per workflow (platform admins; an optional shipped workflow starts off): only new starts change.
async function switchActive(
  readJson: ReadJsonFn, item: ListedWorkflow, active: boolean, setSwitching: Dispatch<SetStateAction<string | null>>,
  setProblem: Dispatch<SetStateAction<string | null>>, setOverview: Dispatch<SetStateAction<WorkflowsOverview | null>>,
) {
  setSwitching(item.id);
  setProblem(null);
  try {
    await readJson<unknown>(flowActivePath(item.id), {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ active }),
    });
    setOverview((current) => current && {
      ...current, flows: current.flows.map((row) => (row.flowId === item.id ? { ...row, isActive: active } : row)),
    });
  } catch (error) {
    setProblem(error instanceof Error ? error.message : `${item.title || item.key} could not be switched ${active ? "on" : "off"}.`);
  } finally {
    setSwitching(null);
  }
}

export function useWorkflowListState(readJson: ReadJsonFn) {
  const { openAdminTab } = useAdminNavigation();
  const [overview, setOverview] = useState<WorkflowsOverview | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [capability, setCapability] = useState("");
  const [scope, setScope] = useState<ScopeFilter>("all");
  const [kind, setKind] = useState<KindFilter>("all");
  const [filtersOpen, setFiltersOpen] = useState(false);
  const [open, setOpen] = useState<OpenWorkflow>(() => readOpenWorkflow(window.location.search));
  // A create request for a flow (`new_flow`, from "+ New workflow" or a workspace's link) opens the builder's drawer.
  const [creatingFlow, setCreatingFlow] = useState(() => new URLSearchParams(window.location.search).get(NEW_FLOW_PARAM) === "1");
  const [showTestFlows, setShowTestFlows] = useState(false);
  // Unsaved edits in the open editor (both editors report them); leaving waits for the ConfirmDialog.
  const [dirty, setDirty] = useState(false);
  const [pendingLeave, setPendingLeave] = useState<(() => void) | null>(null);
  const leave = (action: () => void) => {
    const pending = requestLeave(dirty, () => { setDirty(false); action(); });
    if (pending) setPendingLeave(() => pending);
  };

  const load = useCallback(async () => {
    try {
      setOverview(readWorkflowsOverview(await readJson<unknown>(WORKFLOWS_OVERVIEW_PATH)));
      setProblem(null);
    } catch (error) {
      setProblem(error instanceof Error ? error.message : "The workflows could not be loaded.");
    }
  }, [readJson]);
  useEffect(() => { void load(); }, [load]);

  const [switching, setSwitching] = useState<string | null>(null);
  const toggleActive = (item: ListedWorkflow, active: boolean) =>
    switchActive(readJson, item, active, setSwitching, setProblem, setOverview);
  return {
    openAdminTab, overview, problem, setProblem, query, setQuery, capability, setCapability, scope, setScope, kind, setKind,
    filtersOpen, setFiltersOpen, open, setOpen, creatingFlow, setCreatingFlow, showTestFlows, setShowTestFlows, setDirty,
    pendingLeave, setPendingLeave, leave, load, switching, toggleActive,
  };
}

export type WorkflowListState = ReturnType<typeof useWorkflowListState>;

// Opens the flow builder's create drawer on this page's canvas.
export function startNewFlow(state: WorkflowListState, onListView: (view: WorkflowsListView) => void) {
  const url = new URL(listUrl(window.location.href, "canvas", null), window.location.origin);
  url.searchParams.set(NEW_FLOW_PARAM, "1");
  window.history.replaceState(window.history.state, "", `${url.pathname}${url.search}${url.hash}`);
  state.setOpen(null);
  state.setCreatingFlow(true);
  onListView("canvas");
}
