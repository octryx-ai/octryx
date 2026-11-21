// The designer's actions on the selection: delete, copy and paste, group and ungroup, and undo and redo.
import { useCallback, useMemo, type Dispatch, type SetStateAction } from "react";
import type { Point } from "../phasedGraphTypes";
import { copyItems, paste } from "./modelClipboard";
import { createGroup, dissolveGroup } from "./modelGroups";
import { redo, undo, type History } from "./modelHistory";
import { removable, removeItems, setPositions } from "./modelEditing";
import { type DesignGroup, type DesignModel } from "./modelCore";
import type { useDesignerSelection } from "./useDesignerEditorState";

export function useDesignerSelectionActions({ model, positions, currentGroups, selection, setHistory, setNotice }: {
  model: DesignModel;
  positions: Map<string, Point>;
  currentGroups: DesignGroup[];
  selection: ReturnType<typeof useDesignerSelection>;
  setHistory: Dispatch<SetStateAction<History>>;
  setNotice: (notice: string | null) => void;
}) {
  const { selected, setSelected, edgeId, groupId, setGroupId, clip, setClip, setFocus, change, selectOnly } = selection;
  const selectedNodes = useMemo(() => model.nodes.filter((node) => selected.has(node.id)), [model, selected]);
  const deleteSelection = useCallback(() => {
    const nodes = selectedNodes.filter(removable).map((node) => node.id);
    if (!nodes.length && !edgeId) return;
    change((current) => removeItems(current, nodes, edgeId ? [edgeId] : []));
    selectOnly([]);
  }, [selectedNodes, edgeId, change, selectOnly]);
  const copySelection = useCallback(() => {
    const copied = copyItems(setPositions(model, positions), [...selected]);
    if (copied) {
      setClip(copied);
      setNotice(`Copied ${copied.nodes.length === 1 ? "1 box" : `${copied.nodes.length} boxes`}. Paste with Ctrl+V or ⌘V.`);
    }
  }, [model, positions, selected, setClip, setNotice]);
  const pasteClip = useCallback(() => {
    if (!clip) return;
    const result = paste(model, clip);
    change(() => result.model);
    selectOnly(result.ids);
    if (result.ids[0]) setFocus({ id: result.ids[0], nonce: Date.now() });
  }, [clip, model, change, selectOnly, setFocus]);
  const groupSelection = useCallback(() => {
    const result = createGroup(model, [...selected], `Group ${currentGroups.length + 1}`, currentGroups);
    if (!result.id) return;
    change(() => result.model);
    setSelected(new Set());
    setGroupId(result.id);
  }, [model, selected, currentGroups, change, setSelected, setGroupId]);
  const groupOfSelection = groupId ?? currentGroups.find((group) => group.members.some((id) => selected.has(id)))?.id ?? null;
  const ungroup = useCallback(() => {
    if (!groupOfSelection) return;
    change((current) => dissolveGroup(current, groupOfSelection, currentGroups));
    setGroupId(null);
  }, [groupOfSelection, currentGroups, change, setGroupId]);
  const doUndo = useCallback(() => setHistory(undo), [setHistory]);
  const doRedo = useCallback(() => setHistory(redo), [setHistory]);
  return { selectedNodes, deleteSelection, copySelection, pasteClip, groupSelection, groupOfSelection, ungroup, doUndo, doRedo };
}
