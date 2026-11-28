// Agents & workflows → Workflows: the list of workflows (they run in phases) and Check results as a tab. The list is
// the entry; a row opens that workflow in the designer (`tab=workflowDesigner`, D2b1), which takes the whole window
// until "← All workflows" (designer D2a). Page ids address the views: `tab=workflowList` is the list,
// `tab=workflowChecks` the results; a link with `phased` opens its workflow directly. "New workflow" starts an empty
// canvas (Start and End).
import { useState, type ReactNode } from "react";
import { SegmentedTabs } from "../../../../layout/SegmentedTabs";

import { useAdminNavigation } from "../../../adminNavigation";
import type { ReadJsonFn } from "../../../hooks/useAdminTabLoader.types";
import type { AdminTab } from "../../../types/adminPanelTypes.governance";
import "../agentsWorkflows.css";
import "../../adminChannels.css";
import { PhasedWorkflowEditor } from "../canvas/PhasedWorkflowEditor";
import { PHASED_CREATE_PATH, type PhasedView } from "../canvas/phasedWorkflowModel";
import { CheckResultsTable } from "./CheckResultsTable";
import { WorkflowFilters } from "./WorkflowFilters";
import { WorkflowTable } from "./WorkflowTable";
import { ConfirmDialog } from "../../confirm/ConfirmDialog";
import {
  filterListed, listUrl, listedWorkflows, readListView, type ListedWorkflow, type OpenWorkflow,
  type WorkflowsListView,
} from "./workflowListModel";
import { ACTIVE_SWITCH_HINT } from "./workflowsModel";
import { useWorkflowListState, type WorkflowListState } from "./useWorkflowListState";

export type WorkflowsView = "list" | "checks" | "designer";

export const WORKFLOWS_VIEW_TABS: { view: WorkflowsView; tab: AdminTab; label: string }[] = [
  { view: "list", tab: "workflowList", label: "Workflows" },
  { view: "checks", tab: "workflowChecks", label: "Check results" },
];

type WorkflowsPageProps = { view: WorkflowsView; readJson: ReadJsonFn };

export function WorkflowsPage({ view, readJson }: WorkflowsPageProps) {
  const { openAdminTab } = useAdminNavigation();
  const [listView, setListView] = useState<WorkflowsListView>(() => readListView(window.location.search));
  // An open workflow takes the whole window: no tabs, no list, no filters; its editor has "← All workflows". The
  // designer page is always the canvas.
  const canvas = view === "designer" || (view === "list" && listView === "canvas");
  return (
    <div className={`aw-page${canvas ? " aw-page--canvas" : ""}`} data-testid="workflows-page">
      {canvas ? null : (
        <div className="aw-tabs-host">
          <SegmentedTabs label="Workflows views" idPrefix="workflows" value={view}
            onChange={(key) => { const item = WORKFLOWS_VIEW_TABS.find((entry) => entry.view === key); if (item) openAdminTab(item.tab); }}
            tabs={WORKFLOWS_VIEW_TABS.map((item) => ({ key: item.view, label: item.label }))} />
        </div>
      )}
      {view === "checks" ? (
        <CheckResultsTable readJson={readJson} />
      ) : (
        <WorkflowList readJson={readJson} listView={view === "designer" ? "canvas" : listView}
          onListView={setListView} designer={view === "designer"} />
      )}
    </div>
  );
}

type WorkflowListProps = {
  readJson: ReadJsonFn;
  listView: WorkflowsListView;
  onListView: (view: WorkflowsListView) => void;
  // The designer page (`tab=workflowDesigner`): a workflow that runs in phases, or the start of a new one.
  designer?: boolean;
};

// "New workflow": a draft that runs in phases with a Start and an End, opened in the designer.
async function createPhased(
  readJson: ReadJsonFn, state: WorkflowListState, setCreating: (value: boolean) => void,
  openWorkflow: (next: OpenWorkflow) => void,
) {
  setCreating(true);
  state.setProblem(null);
  try {
    const created = await readJson<PhasedView>(PHASED_CREATE_PATH, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ title: "New workflow" }),
    });
    openWorkflow(created.flow_id);
  } catch (error) {
    state.setProblem(error instanceof Error ? error.message : "The new workflow could not be made.");
  } finally {
    setCreating(false);
  }
}

function WorkflowList({ readJson, listView, onListView, designer = false }: WorkflowListProps) {
  const state = useWorkflowListState(readJson);
  const { openAdminTab, overview, query, capability, scope, open, setOpen, showTestFlows, leave, load } = state;

  const items = overview ? listedWorkflows(overview) : [];
  const rows = filterListed(items, { query, capability, scope, showTestFlows });

  // The address carries the open workflow; none is the list.
  const switchTo = (next: OpenWorkflow) => {
    window.history.replaceState(window.history.state, "", listUrl(window.location.href, next ? "canvas" : "table", next));
    setOpen(next);
    onListView(next ? "canvas" : "table");
  };
  const openWorkflow = (next: OpenWorkflow) => {
    switchTo(next);
    if (next && !designer) openAdminTab("workflowDesigner");
  };
  const openItem = (item: ListedWorkflow) => leave(() => openWorkflow(item.id));
  const toList = () => leave(() => {
    switchTo(null);
    if (designer) openAdminTab("workflowList");
    void load();
  });
  const [creating, setCreating] = useState(false);
  const newWorkflow = () => leave(() => createPhased(readJson, state, setCreating, openWorkflow));
  const confirmLeave = <LeaveConfirm state={state} />;

  if (listView === "canvas") {
    return (
      <WorkflowCanvasView state={state} designer={designer} shown={open} creating={creating}
        newWorkflow={newWorkflow} toList={toList} readJson={readJson} confirmLeave={confirmLeave} />
    );
  }
  return (
    <WorkflowListView state={state} rows={rows} creating={creating} newWorkflow={newWorkflow} openItem={openItem}
      confirmLeave={confirmLeave} />
  );
}

function LeaveConfirm({ state: { pendingLeave, setPendingLeave } }: { state: WorkflowListState }) {
  return pendingLeave ? (
    <ConfirmDialog title="Leave this workflow?" confirmLabel="Discard edits" onCancel={() => setPendingLeave(null)}
      onConfirm={() => { const action = pendingLeave; setPendingLeave(null); action(); }}>
      <p>Its unsaved edits are discarded. Save a draft first to keep them.</p>
    </ConfirmDialog>
  ) : null;
}

type CanvasViewProps = {
  state: WorkflowListState; designer: boolean; shown: OpenWorkflow; creating: boolean;
  newWorkflow: () => void; toList: () => void; readJson: ReadJsonFn; confirmLeave: ReactNode;
};

function WorkflowCanvasView({
  state, designer, shown, creating, newWorkflow, toList, readJson, confirmLeave,
}: CanvasViewProps) {
  const { problem, setDirty } = state;
  return (
    <>
      {designer && !shown ? (
        <div className="flow-builder aw-designer-start" data-testid="designer">
          <div className="flow-builder__topbar">
            <div className="flow-builder__title-block">
              <span className="admin-panel__eyebrow">Workflow designer</span>
              <h2>Draw a new workflow, or open one from the list</h2>
            </div>
            <div className="flow-builder__header-actions">
              <button type="button" className="admin-panel__action-btn" onClick={toList}>← All workflows</button>
              <button type="button" className="admin-panel__action-btn admin-panel__action-btn--primary" data-testid="designer-new"
                disabled={creating} onClick={newWorkflow}>New workflow</button>
            </div>
          </div>
          {problem ? <p className="admin-panel__error" role="alert">{problem}</p> : null}
        </div>
      ) : null}
      {shown ? (
        <PhasedWorkflowEditor key={shown} flowId={shown} readJson={readJson} onDirtyChange={setDirty} onBack={toList} />
      ) : null}
      {confirmLeave}
    </>
  );
}

type ListViewProps = {
  state: WorkflowListState; rows: ListedWorkflow[]; creating: boolean; newWorkflow: () => void;
  openItem: (item: ListedWorkflow) => void; confirmLeave: ReactNode;
};

function WorkflowListView({ state, rows, creating, newWorkflow, openItem, confirmLeave }: ListViewProps) {
  const { filtersOpen, capability, setCapability, scope, setScope, showTestFlows, setShowTestFlows,
    problem, overview, toggleActive, switching } = state;
  return (
    <>
      <div className="aw-list-head">
        <WorkflowToolbar state={state} creating={creating} newWorkflow={newWorkflow} />
        {filtersOpen ? (
          <WorkflowFilters capability={capability} onCapability={setCapability}
            scope={scope} onScope={setScope} showTestFlows={showTestFlows} onShowTestFlows={setShowTestFlows} />
        ) : null}
        {problem ? <p className="admin-panel__error" role="alert">{problem}</p> : null}
        {!overview && !problem ? <p className="admin-panel__hint" role="status">Loading workflows…</p> : null}
        {overview && rows.length === 0 ? <div className="admin-panel__empty-state">No workflow matches this search.</div> : null}
      </div>
      {rows.length ? <p className="admin-panel__hint" data-testid="workflow-active-hint">{ACTIVE_SWITCH_HINT}</p> : null}
      {rows.length ? <WorkflowTable items={rows} usageWindowDays={overview?.usageWindowDays ?? 30} onOpen={openItem}
        onToggleActive={(item, active) => void toggleActive(item, active)} busyId={switching} /> : null}
      {confirmLeave}
    </>
  );
}

type ToolbarProps = { state: WorkflowListState; creating: boolean; newWorkflow: () => void };

function WorkflowToolbar({ state, creating, newWorkflow }: ToolbarProps) {
  const { query, setQuery, filtersOpen, setFiltersOpen, capability, scope, showTestFlows } = state;
  const filtered = Boolean(capability || scope !== "all" || showTestFlows);
  return (
    <div className="aw-toolbar">
      <input className="admin-users__toolbar-input" value={query} aria-label="Search workflows"
        placeholder="Search key, title, description" onChange={(event) => setQuery(event.target.value)} />
      <button type="button" className="admin-panel__action-btn" aria-expanded={filtersOpen} aria-controls="workflows-filters"
        onClick={() => setFiltersOpen((current) => !current)}>
        {filtersOpen ? "Hide filters" : filtered ? "Filters (on)" : "Filters"}
      </button>
      <span className="aw-toolbar__spacer" />
      <button type="button" className="admin-panel__action-btn admin-panel__action-btn--primary" data-testid="designer-new"
        disabled={creating} onClick={newWorkflow} title="Starts an empty canvas with a Start and an End">
        New workflow
      </button>
    </div>
  );
}
