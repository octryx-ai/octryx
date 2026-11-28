// The Workflows list, the page's entry: every workflow with what tells them apart at a glance (name, status and
// version, when it last changed and by whom, how often it ran). A row opens the workflow on the canvas.
import type { KeyboardEvent } from "react";

import { StatusLabel } from "../../../../layout/StatusLabel";
import { lastChangedLabel, listedStatusLabel, type ListedWorkflow } from "./workflowListModel";

type WorkflowTableProps = {
  items: ListedWorkflow[];
  usageWindowDays: number;
  onOpen: (item: ListedWorkflow) => void;
  // Switches a workflow on or off; a row whose switch is being saved is busy. Without it there is no switch.
  onToggleActive?: (item: ListedWorkflow, active: boolean) => void;
  busyId?: string | null;
};

export function WorkflowTable({ items, usageWindowDays, onOpen, onToggleActive, busyId = null }: WorkflowTableProps) {
  const onRowKey = (event: KeyboardEvent, item: ListedWorkflow) => {
    if (event.key === "Enter") onOpen(item);
  };
  const runs = `Runs (${usageWindowDays} d)`;
  return (
    <table className="admin-panel__table aw-cards aw-table">
      <thead>
        <tr>
          <th>Workflow</th><th>Status</th>{onToggleActive ? <th>On</th> : null}<th>Last changed</th><th>By</th><th>{runs}</th>
        </tr>
      </thead>
      <tbody>
        {items.map((item) => {
          const changed = lastChangedLabel(item);
          return (
            <tr key={item.id} tabIndex={0} onClick={() => onOpen(item)} onKeyDown={(event) => onRowKey(event, item)}
              data-testid={`workflow-row-${item.key}`} aria-label={`Open ${item.title || item.key}`}>
              <td data-l="Workflow"><div className="aw-name">{item.title || item.key}</div><div className="aw-sub aw-mono">{item.key}</div></td>
              <td data-l="Status">
                <StatusLabel label={listedStatusLabel(item)} tone={item.row.status === "published" ? "neutral" : "attention"} />
              </td>
              {onToggleActive ? (
                <td data-l="On" onClick={(event) => event.stopPropagation()} onKeyDown={(event) => event.stopPropagation()}>
                  <label className="aw-switch">
                    <input type="checkbox" role="switch" checked={item.row.isActive} disabled={busyId === item.id}
                      aria-label={`${item.title || item.key} on`} data-testid={`workflow-active-${item.key}`}
                      onChange={(event) => onToggleActive(item, event.target.checked)} />
                    <span>{item.row.isActive ? "On" : "Off"}</span>
                  </label>
                </td>
              ) : null}
              <td data-l="Last changed" title={changed.title || undefined}>{changed.text}</td>
              <td data-l="By">{item.row.updatedBy ?? "—"}</td>
              <td data-l={runs} className="aw-num">{item.row.used}</td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}
