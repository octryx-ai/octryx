import type { Dispatch, MutableRefObject, SetStateAction } from "react";
import { useEffect, useMemo, useRef } from "react";

import { buildComposerDraftKey } from "./appHelpers";
import { takeComposerPrefill } from "./composerPrefill";
import type { DraftAttachment } from "./useComposerInteractions.types";

export function useComposerDraftLifecycle({
  selectedSessionId,
  selectedProjectId,
  selectedRuntimeTargetId,
  selectedModeKey,
  composerValue,
  setComposerValue,
  setDraftAttachments,
  setComposerHistoryIndex,
  composerNavigationDraftRef,
  textareaRef,
}: {
  selectedSessionId: string | null;
  selectedProjectId: string;
  selectedRuntimeTargetId: string;
  selectedModeKey: string;
  composerValue: string;
  setComposerValue: Dispatch<SetStateAction<string>>;
  setDraftAttachments: Dispatch<SetStateAction<DraftAttachment[]>>;
  setComposerHistoryIndex: Dispatch<SetStateAction<number>>;
  composerNavigationDraftRef: MutableRefObject<string>;
  textareaRef: MutableRefObject<HTMLTextAreaElement | null>;
}) {
  const composerDraftKey = useMemo(
    () =>
      buildComposerDraftKey({
        sessionId: selectedSessionId,
        projectId: selectedProjectId,
        runtimeTargetId: selectedRuntimeTargetId,
        modeKey: selectedModeKey,
      }),
    [
      selectedModeKey,
      selectedProjectId,
      selectedRuntimeTargetId,
      selectedSessionId,
    ],
  );

  // A new chat opened with a hand-off ("Ask in chat") keeps it while the draft key settles (runtime target, mode),
  // until the person changes or sends it.
  const handOff = useRef<{ projectId: string; text: string; shown: boolean } | null>(null);

  useEffect(() => {
    let handed = "";
    if (!selectedSessionId) {
      if (handOff.current?.projectId === selectedProjectId) handed = handOff.current.text;
      else {
        handed = takeComposerPrefill(window.localStorage, selectedProjectId);
        if (handed) handOff.current = { projectId: selectedProjectId, text: handed, shown: false };
      }
    }
    const savedDraft = window.localStorage.getItem(composerDraftKey) || handed;
    setComposerValue(savedDraft);
    setDraftAttachments([]);
    setComposerHistoryIndex(-1);
    composerNavigationDraftRef.current = "";
  }, [
    composerDraftKey,
    setComposerHistoryIndex,
    setComposerValue,
    setDraftAttachments,
    composerNavigationDraftRef,
  ]);

  useEffect(() => {
    if (!textareaRef.current) {
      return;
    }
    textareaRef.current.style.height = "0px";
    textareaRef.current.style.height = `${Math.min(textareaRef.current.scrollHeight, 240)}px`;
  }, [composerValue, textareaRef]);

  useEffect(() => {
    window.localStorage.setItem(composerDraftKey, composerValue);
    const current = handOff.current;
    if (current && composerValue === current.text) current.shown = true;
    else if (current?.shown) handOff.current = null;
  }, [composerDraftKey, composerValue]);

  return { composerDraftKey };
}
