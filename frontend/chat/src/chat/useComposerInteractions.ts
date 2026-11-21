import { createComposerInteractionHandlers } from "./useComposerInteractions.handlers";
import { SLASH_COMMANDS } from "./useComposerInteractions.keys";
import { useComposerArtifactDraftListener } from "./useComposerArtifactDraftListener";
import type {
  DraftAttachment,
  UseComposerInteractionsArgs,
} from "./useComposerInteractions.types";

export function useComposerInteractions(args: UseComposerInteractionsArgs) {
  const { composerDraftKey, setComposerValue, textareaRef } = args;
  const handlers = createComposerInteractionHandlers(args);

  useComposerArtifactDraftListener({
    composerDraftKey,
    setComposerValue,
    textareaRef,
  });

  return {
    SLASH_COMMANDS,
    ...handlers,
  };
}
