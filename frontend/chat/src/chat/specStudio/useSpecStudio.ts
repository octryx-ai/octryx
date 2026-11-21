import { useCallback, useEffect, useRef, useState } from "react";

import { approveStudio, errorText, loadStudio, reviseStudio, saveChange, type StudioChange } from "./specStudioApi";
import type { StudioPayload } from "./specStudioModel";

// The Studio's data and its save state per section. A change is saved at once; while a save runs the section says
// "Saving…", then "Saved", or the refusal in words with Retry. Leaving the page while a save runs or a text is not
// saved yet asks first (beforeunload), so nothing is lost silently.

export type SectionKey = "design" | "questions" | "rules" | "acceptance" | "comments" | "approve";
export type SaveState = { state: "idle" | "saving" | "saved" | "failed"; message?: string; retry?: () => void };

export function useSpecStudio(runId: string) {
  const [payload, setPayload] = useState<StudioPayload | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [saves, setSaves] = useState<Partial<Record<SectionKey, SaveState>>>({});
  const pending = useRef(0);
  const dirty = useRef(new Set<string>());

  const reload = useCallback(() => {
    setLoadError(null);
    loadStudio(runId).then(setPayload).catch((error) => setLoadError(errorText(error)));
  }, [runId]);
  useEffect(reload, [reload]);

  useEffect(() => {
    const guard = (event: BeforeUnloadEvent) => {
      if (pending.current > 0 || dirty.current.size > 0) {
        event.preventDefault();
        event.returnValue = "";
      }
    };
    window.addEventListener("beforeunload", guard);
    return () => window.removeEventListener("beforeunload", guard);
  }, []);

  const save = useCallback(
    (section: SectionKey, change: StudioChange): Promise<StudioPayload | null> => {
      pending.current += 1;
      setSaves((current) => ({ ...current, [section]: { state: "saving" } }));
      return saveChange(runId, change)
        .then((next) => {
          setPayload(next);
          setSaves((current) => ({ ...current, [section]: { state: "saved" } }));
          return next;
        })
        .catch((error) => {
          const retry = () => void save(section, change);
          setSaves((current) => ({ ...current, [section]: { state: "failed", message: errorText(error), retry } }));
          return null;
        })
        .finally(() => {
          pending.current -= 1;
        });
    },
    [runId],
  );

  const decide = useCallback(
    (action: "approve" | "revise") => {
      pending.current += 1;
      setSaves((current) => ({ ...current, approve: { state: "saving" } }));
      return (action === "approve" ? approveStudio(runId) : reviseStudio(runId))
        .then((next) => {
          setPayload(next);
          setSaves((current) => ({ ...current, approve: { state: "saved" } }));
        })
        .catch((error) => {
          setSaves((current) => ({ ...current, approve: { state: "failed", message: errorText(error),
            retry: () => void decide(action) } }));
        })
        .finally(() => {
          pending.current -= 1;
        });
    },
    [runId],
  );

  // A text the product owner is typing (comment, own answer, criterion note): unsaved until it is sent.
  const markDirty = useCallback((key: string, isDirty: boolean) => {
    if (isDirty) dirty.current.add(key);
    else dirty.current.delete(key);
  }, []);

  return { payload, loadError, reload, saves, save, decide, markDirty };
}

export type SpecStudioHandle = ReturnType<typeof useSpecStudio>;
