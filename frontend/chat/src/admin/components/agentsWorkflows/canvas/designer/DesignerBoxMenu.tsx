// The designer's box menu: connect the box to another one, copy or delete it.
import { kindName } from "./inspector/labels";
import { removable } from "./modelEditing";
import { type DesignModel } from "./modelCore";
import type { DefNode } from "./types";

export function DesignerBoxMenu({ menu, menuNode, model, connectBoxes, setMenu, copySelection, deleteSelection }: {
  menu: { id: string; connect: boolean }; menuNode: DefNode; model: DesignModel;
  connectBoxes: (source: string, target: string) => void;
  setMenu: (menu: { id: string; connect: boolean } | null) => void;
  copySelection: () => void; deleteSelection: () => void;
}) {
  return (
    <div className="dsg__menu" role="menu" aria-label={`${menuNode.label || kindName(menuNode.type)}: actions`}>
      <strong>{menuNode.label || kindName(menuNode.type)}</strong>
      {menu.connect ? (
        <>
          <span className="admin-panel__hint">Connect to…</span>
          {model.nodes.filter((item) => item.id !== menuNode.id && item.type !== "start").map((item) => (
            <button key={item.id} type="button" role="menuitem" className="admin-panel__action-btn" data-testid="designer-connect-target"
              data-node-id={item.id} onClick={() => connectBoxes(menuNode.id, item.id)}>
              {item.label || kindName(item.type)} ({kindName(item.type)})
            </button>
          ))}
        </>
      ) : (
        <>
          {menuNode.type !== "outcome" ? (
            <button type="button" role="menuitem" className="admin-panel__action-btn" data-testid="designer-connect-to"
              onClick={() => setMenu({ id: menuNode.id, connect: true })}>Connect to…</button>
          ) : null}
          {removable(menuNode) ? (
            <>
              <button type="button" role="menuitem" className="admin-panel__action-btn" onClick={() => { copySelection(); setMenu(null); }}>Copy</button>
              <button type="button" role="menuitem" className="admin-panel__action-btn" onClick={() => { deleteSelection(); setMenu(null); }}>Delete</button>
            </>
          ) : null}
        </>
      )}
      <button type="button" className="admin-panel__action-btn" onClick={() => setMenu(null)}>Cancel</button>
    </div>
  );
}
