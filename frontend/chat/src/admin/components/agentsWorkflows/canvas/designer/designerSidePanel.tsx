// The designer's side panel content for the selection: one box, an arrow, a group or several boxes.
import { SidePanel } from "../../../../../layout/SidePanel";
import { EdgeInspector } from "./inspector/EdgeInspector";
import { kindName } from "./inspector/labels";
import { nodeConfigIssues } from "./inspector/nodeIssues";
import { NodeInspector } from "./inspector/NodeInspector";
import { edgeIssues } from "./inspector/patch";
import { boxName } from "./issues";
import { findNode, type DesignGroup, type DesignModel } from "./modelCore";
import { removable, route, updateEdge, updateNode } from "./modelEditing";
import { renameGroup } from "./modelGroups";
import type { DefEdge, DefNode, DesignerCatalog } from "./types";

export function designerSidePanel({
  node, edge, group, selectedNodes, model, catalog, busy, dirty, currentGroups, change, closePanel,
  copySelection, deleteSelection, groupSelection, ungroup, onOpenPhase,
}: {
  node: DefNode | null; edge: DefEdge | undefined; group: DesignGroup | null; selectedNodes: DefNode[];
  model: DesignModel; catalog: DesignerCatalog; busy: boolean; dirty: boolean;
  currentGroups: DesignGroup[];
  change: (update: (current: DesignModel) => DesignModel, key?: string) => void;
  closePanel: () => void; copySelection: () => void; deleteSelection: () => void; groupSelection: () => void;
  ungroup: () => void; onOpenPhase: (id: string) => void;
}) {
  const close = (
    <button type="button" className="ds-panel__close" aria-label="Close the panel" onClick={closePanel}>✕</button>
  );
  let panel = null;
  if (node) {
    panel = (
      <SidePanel mode="page" title={node.label || kindName(node.type)} subtitle={kindName(node.type)} onClose={closePanel}
        headerActions={close} testId="designer-panel"
        footer={(
          <>
            {node.type === "phase" ? (
              <button type="button" className="admin-panel__action-btn" disabled={dirty}
                title={dirty ? "Save the draft first" : "Open this step's steps and checks on their own canvas"}
                onClick={() => onOpenPhase(node.id)}>Open steps</button>
            ) : null}
            {removable(node) ? (
              <>
                <button type="button" className="admin-panel__action-btn" onClick={copySelection}>Copy</button>
                <button type="button" className="admin-panel__action-btn" onClick={deleteSelection}>Delete</button>
              </>
            ) : null}
          </>
        )}>
        <NodeInspector node={node} nodes={model.nodes} edges={model.edges} catalog={catalog} editable={!busy}
          issues={nodeConfigIssues(node, model.nodes, catalog)}
          onChange={(patch) => change((current) => updateNode(current, node.id, patch), `node:${node.id}`)}
          onRoute={(when, target) => change((current) => route(current, node.id, when, target))} />
      </SidePanel>
    );
  } else if (edge) {
    panel = (
      <SidePanel mode="page" title={edge.kind === "loop" ? "Way back" : "Arrow"}
        subtitle={`${boxName(findNode(model, edge.source))} → ${boxName(findNode(model, edge.target))}`}
        onClose={closePanel} headerActions={close} testId="designer-panel"
        footer={<button type="button" className="admin-panel__action-btn" onClick={deleteSelection}>Delete</button>}>
        <EdgeInspector edge={edge} edges={model.edges} nodes={model.nodes} catalog={catalog} editable={!busy}
          issues={edgeIssues(edge, model.edges, model.nodes, catalog)}
          onChange={(patch) => change((current) => updateEdge(current, edge.id, patch), `edge:${edge.id}`)} />
      </SidePanel>
    );
  } else if (group) {
    panel = (
      <SidePanel mode="page" title={group.label || "Group"} subtitle={`Group · ${group.members.length} boxes`} onClose={closePanel}
        headerActions={close} testId="designer-panel"
        footer={<button type="button" className="admin-panel__action-btn" onClick={ungroup}>Ungroup</button>}>
        <div className="aw-inspector dsi">
          <label className="admin-panel__field">
            <span>Name of the group</span>
            <input className="admin-panel__input" value={group.label}
              onChange={(event) => change((current) => renameGroup(current, group.id, event.target.value, currentGroups), `group:${group.id}`)} />
          </label>
          <p className="admin-panel__hint">A group is only how the chart is drawn: it folds into one box. Ungroup keeps every box.</p>
        </div>
      </SidePanel>
    );
  } else if (selectedNodes.length > 1) {
    panel = (
      <SidePanel mode="page" title={`${selectedNodes.length} boxes`} subtitle="Selected" onClose={closePanel} headerActions={close}
        testId="designer-panel"
        footer={(
          <>
            <button type="button" className="admin-panel__action-btn" onClick={groupSelection}>Group</button>
            <button type="button" className="admin-panel__action-btn" onClick={copySelection}>Copy</button>
            <button type="button" className="admin-panel__action-btn" onClick={deleteSelection}>Delete</button>
          </>
        )}>
        <p className="admin-panel__hint">{selectedNodes.map((item) => item.label || kindName(item.type)).join(" · ")}</p>
      </SidePanel>
    );
  }
  return panel;
}
