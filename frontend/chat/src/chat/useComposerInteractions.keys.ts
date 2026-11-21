// Composer key handling: slash commands, history navigation with the arrow keys, Escape and Enter to send.
import type { KeyboardEvent } from "react";

import type {
  ComposerInteractionHandlers,
  SlashCommandOption,
  UseComposerInteractionsArgs,
} from "./useComposerInteractions.types";

export const SLASH_COMMANDS: SlashCommandOption[] = [
  {
    name: "generate-task-from-chat",
    description: "Generate a task definition from this conversation",
  },
  {
    name: "generate-workflow",
    description: "Generate a draft workflow from this conversation",
  },
];

export function createComposerKeyDownHandler(
  args: UseComposerInteractionsArgs,
): ComposerInteractionHandlers["handleComposerKeyDown"] {
  const {
    composerValue,
    setComposerValue,
    atMention,
    setAtMention,
    slashCommand,
    setSlashCommand,
    composerHistory,
    composerHistoryIndex,
    setComposerHistoryIndex,
    composerNavigationDraftRef,
    handleSend,
  } = args;

  const handleComposerKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === "Escape" && (atMention.open || slashCommand.open)) {
      event.preventDefault();
      setAtMention({ open: false, query: "", startPos: -1 });
      setSlashCommand({ open: false, query: "" });
      return;
    }
    if (
      event.key === "ArrowUp" &&
      !event.shiftKey &&
      !atMention.open &&
      !slashCommand.open &&
      composerHistory.length > 0 &&
      event.currentTarget.selectionStart === 0 &&
      event.currentTarget.selectionEnd === 0
    ) {
      event.preventDefault();
      if (composerHistoryIndex === -1) {
        composerNavigationDraftRef.current = composerValue;
        setComposerHistoryIndex(0);
        setComposerValue(composerHistory[0] || "");
        return;
      }
      const nextIndex = Math.min(
        composerHistoryIndex + 1,
        composerHistory.length - 1,
      );
      setComposerHistoryIndex(nextIndex);
      setComposerValue(composerHistory[nextIndex] || "");
      return;
    }
    if (
      event.key === "ArrowDown" &&
      !event.shiftKey &&
      composerHistoryIndex >= 0 &&
      !atMention.open &&
      !slashCommand.open &&
      event.currentTarget.selectionStart === event.currentTarget.value.length &&
      event.currentTarget.selectionEnd === event.currentTarget.value.length
    ) {
      event.preventDefault();
      if (composerHistoryIndex === 0) {
        setComposerHistoryIndex(-1);
        setComposerValue(composerNavigationDraftRef.current);
        composerNavigationDraftRef.current = "";
        return;
      }
      const nextIndex = composerHistoryIndex - 1;
      setComposerHistoryIndex(nextIndex);
      setComposerValue(composerHistory[nextIndex] || "");
      return;
    }
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      if (slashCommand.open) {
        const match = SLASH_COMMANDS.find((command) =>
          command.name.startsWith(slashCommand.query),
        );
        if (match) {
          setComposerValue("");
          setSlashCommand({ open: false, query: "" });
          void handleSend(`/${match.name}`);
          return;
        }
      }
      void handleSend();
    }
  };

  return handleComposerKeyDown;
}
