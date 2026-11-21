// The designer canvas's editing hooks: selecting boxes and arrows, connecting, dropping a box, the box menu and groups.
import { useMemo, type Dispatch, type SetStateAction } from "react";
import type { CanvasEditing } from "../phasedCanvasTypes";
import type { Point } from "../phasedGraphTypes";
import type { NodeKind } from "./types";

type DesignerCanvasEditingArgs = {
  selected: ReadonlySet<string>;
  edgeId: string | null;
  focus: { id: string; nonce: number } | null;
  selectOnly: (ids: string[]) => void;
  connectBoxes: (source: string, target: string) => void;
  addBox: (kind: NodeKind, at?: Point) => void;
  setSelected: Dispatch<SetStateAction<ReadonlySet<string>>>;
  setEdgeId: Dispatch<SetStateAction<string | null>>;
  setGroupId: Dispatch<SetStateAction<string | null>>;
  setMenu: Dispatch<SetStateAction<{ id: string; connect: boolean } | null>>;
};

export function useDesignerCanvasEditing({
  selected, edgeId, focus, selectOnly, connectBoxes, addBox, setSelected, setEdgeId, setGroupId, setMenu,
}: DesignerCanvasEditingArgs): CanvasEditing {
  return useMemo<CanvasEditing>(() => ({
    selectedIds: selected,
    selectedEdgeId: edgeId,
    onSelectNode: (id, add) => {
      if (!add) {
        selectOnly([id]);
        return;
      }
      setSelected((current) => {
        const next = new Set(current);
        if (next.has(id)) next.delete(id);
        else next.add(id);
        return next;
      });
      setEdgeId(null);
      setGroupId(null);
    },
    onSelectEdge: (id) => {
      setSelected(new Set());
      setEdgeId(id);
      setGroupId(null);
      setMenu(null);
    },
    onClear: () => selectOnly([]),
    onConnect: connectBoxes,
    onDropBox: (kind, at) => addBox(kind, at),
    onMenu: (id) => {
      setSelected(new Set([id]));
      setEdgeId(null);
      setGroupId(null);
      setMenu((current) => (current?.id === id && !current.connect ? null : { id, connect: false }));
    },
    onEditGroup: (id) => {
      setSelected(new Set());
      setEdgeId(null);
      setGroupId(id);
    },
    focus,
  }), [selected, edgeId, selectOnly, connectBoxes, addBox, focus, setSelected, setEdgeId, setGroupId, setMenu]);
}
