// The folded-away filters of the workflow list: capability class, scope and test flows.
import type { ScopeFilter } from "./workflowsModel";

type WorkflowFiltersProps = {
  capability: string;
  onCapability: (capability: string) => void;
  scope: ScopeFilter;
  onScope: (scope: ScopeFilter) => void;
  showTestFlows: boolean;
  onShowTestFlows: (show: boolean) => void;
};

export function WorkflowFilters({
  capability, onCapability, scope, onScope, showTestFlows, onShowTestFlows,
}: WorkflowFiltersProps) {
  return (
    <div className="aw-toolbar" id="workflows-filters" role="group" aria-label="Filters">
      <select className="admin-users__toolbar-select" value={capability} aria-label="Capability class"
        onChange={(event) => onCapability(event.target.value)}>
        <option value="">Any class</option>
        <option value="read_only">Read-only</option>
        <option value="change">Change</option>
        <option value="deliver">Deliver</option>
      </select>
      <select className="admin-users__toolbar-select" value={scope} aria-label="Scope"
        onChange={(event) => onScope(event.target.value as ScopeFilter)}>
        <option value="all">Global + Workspaces</option>
        <option value="global">Global only</option>
        <option value="workspace">Workspaces only</option>
      </select>
      <label className="admin-panel__checkbox">
        <input type="checkbox" checked={showTestFlows} onChange={(event) => onShowTestFlows(event.target.checked)} />
        <span>Show test flows</span>
      </label>
    </div>
  );
}
