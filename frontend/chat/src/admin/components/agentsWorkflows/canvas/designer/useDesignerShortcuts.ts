// Designer keyboard shortcuts: delete, undo/redo, copy and paste, ignored while typing in a field.
import { useEffect } from "react";

import { typing } from "./designerEditorHelpers";
import type { Clipboard } from "./modelClipboard";

export function useDesignerShortcuts({
  deleteSelection, doUndo, doRedo, copySelection, pasteClip, selected, clip,
}: {
  deleteSelection: () => void; doUndo: () => void; doRedo: () => void; copySelection: () => void; pasteClip: () => void;
  selected: ReadonlySet<string>; clip: Clipboard | null;
}) {
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (typing(event.target) || event.defaultPrevented) return;
      const mod = event.metaKey || event.ctrlKey;
      const key = event.key.toLowerCase();
      if ((event.key === "Delete" || event.key === "Backspace") && !mod) {
        event.preventDefault();
        deleteSelection();
      } else if (mod && key === "z") {
        event.preventDefault();
        if (event.shiftKey) doRedo();
        else doUndo();
      } else if (mod && key === "y") {
        event.preventDefault();
        doRedo();
      } else if (mod && key === "c" && selected.size) {
        event.preventDefault();
        copySelection();
      } else if (mod && key === "v" && clip) {
        event.preventDefault();
        pasteClip();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [deleteSelection, doUndo, doRedo, copySelection, pasteClip, selected, clip]);
}
