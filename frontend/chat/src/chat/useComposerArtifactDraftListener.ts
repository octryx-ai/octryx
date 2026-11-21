import { useEffect } from "react";
import type { Dispatch, MutableRefObject, SetStateAction } from "react";

export function useComposerArtifactDraftListener({
  composerDraftKey,
  setComposerValue,
  textareaRef,
}: {
  composerDraftKey: string;
  setComposerValue: Dispatch<SetStateAction<string>>;
  textareaRef: MutableRefObject<HTMLTextAreaElement | null>;
}) {
  useEffect(() => {
    const handleArtifactDraft = (event: Event) => {
      const prompt = String((event as CustomEvent<string>).detail || "").trim();
      if (!prompt) {
        return;
      }
      setComposerValue(prompt);
      window.localStorage.setItem(composerDraftKey, prompt);
      textareaRef.current?.focus();
    };
    window.addEventListener(
      "octryx:artifact-draft",
      handleArtifactDraft as EventListener,
    );
    return () => {
      window.removeEventListener(
        "octryx:artifact-draft",
        handleArtifactDraft as EventListener,
      );
    };
  }, [composerDraftKey, setComposerValue, textareaRef]);
}
