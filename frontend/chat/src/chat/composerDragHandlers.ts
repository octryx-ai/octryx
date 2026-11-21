// Drag-and-drop handlers of the composer: highlight while dragging, upload dropped files.
import type { DragEvent } from "react";

export function composerDragHandlers(
  composerDisabled: boolean,
  setComposerDragActive: (value: boolean) => void,
  uploadDraftFiles: (files: FileList | File[]) => Promise<void>,
) {
  return {
    onDragOver: (event: DragEvent<HTMLDivElement>) => {
      event.preventDefault();
      if (!composerDisabled) {
        setComposerDragActive(true);
      }
    },
    onDragLeave: (event: DragEvent<HTMLDivElement>) => {
      if (
        !event.currentTarget.contains(event.relatedTarget as Node | null)
      ) {
        setComposerDragActive(false);
      }
    },
    onDrop: (event: DragEvent<HTMLDivElement>) => {
      event.preventDefault();
      setComposerDragActive(false);
      if (composerDisabled) {
        return;
      }
      if (event.dataTransfer.files?.length) {
        void uploadDraftFiles(event.dataTransfer.files);
      }
    },
  };
}
