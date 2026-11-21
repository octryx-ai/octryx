import type {
  ComposerInteractionHandlers,
  UseComposerInteractionsArgs,
} from "./useComposerInteractions.types";
import { createComposerKeyDownHandler } from "./useComposerInteractions.keys";
import { createComposerRoutingHandlers } from "./useComposerInteractions.routing";
import { createComposerUploadHandlers } from "./useComposerInteractions.upload";

export function createComposerInteractionHandlers(
  args: UseComposerInteractionsArgs,
): ComposerInteractionHandlers {
  const {
    setComposerValue,
    setAtMention,
    setSlashCommand,
    composerDraftKey,
    textareaRef,
    setEditingMessage,
  } = args;

  const { uploadDraftFiles, removeDraftAttachment } = createComposerUploadHandlers(args);

  const handleComposerChange = (value: string) => {
    setComposerValue(value);
    if (value.startsWith("/") && !value.includes(" ")) {
      setSlashCommand({ open: true, query: value.slice(1).toLowerCase() });
    } else {
      setSlashCommand({ open: false, query: "" });
    }

    const atIdx = value.lastIndexOf("@");
    if (atIdx !== -1) {
      const afterAt = value.slice(atIdx + 1);
      if (!afterAt.includes(" ")) {
        setAtMention({
          open: true,
          query: afterAt.toLowerCase(),
          startPos: atIdx,
        });
        return;
      }
    }
    setAtMention((prev) =>
      prev.open ? { open: false, query: "", startPos: -1 } : prev,
    );
  };

  const {
    handleSelectAtAgent,
    handleAgentGroupChange,
    handleAgentSelection,
  } = createComposerRoutingHandlers(args);

  const handleComposerKeyDown = createComposerKeyDownHandler(args);

  const handleReuseMessage = (content: string) => {
    setComposerValue(content);
    window.localStorage.setItem(composerDraftKey, content);
    textareaRef.current?.focus();
  };

  const handleEditMessage = (messageId: string, content: string) => {
    setEditingMessage({ id: messageId, content });
    setComposerValue(content);
    window.localStorage.setItem(composerDraftKey, content);
    textareaRef.current?.focus();
  };

  const handleCancelEditMessage = () => {
    setEditingMessage(null);
  };

  return {
    uploadDraftFiles,
    removeDraftAttachment,
    handleComposerChange,
    handleSelectAtAgent,
    handleAgentGroupChange,
    handleAgentSelection,
    handleComposerKeyDown,
    handleReuseMessage,
    handleEditMessage,
    handleCancelEditMessage,
  };
}
