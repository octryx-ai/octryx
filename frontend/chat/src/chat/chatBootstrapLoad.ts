// Loads the chat state: a session-only refresh or a switch reads one session's view; otherwise the full bootstrap.
import type { MutableRefObject } from "react";

import type { ChatState } from "../types";
import { chatApiPath, readJson } from "./chatApiClient";
import { bootstrapFailureText } from "./bootstrapFailure";
import { readSessionView, threadListed } from "./chatBootstrapReads";
import type { ChatBootstrapStateArgs, LoadOptions } from "./chatBootstrapTypes";
import { sessionSwitchTarget, viewToState } from "./sessionView";
import { beginStateLoad, isLatestStateLoad, type StateLoadSequence } from "./stateLoadSequence";

export type LoadContext = Pick<ChatBootstrapStateArgs, "chatState" | "setLoading" | "setSending" | "setPendingPrompt" | "setError"> & {
  loadSequence: StateLoadSequence;
  listRefreshFor: MutableRefObject<string | null>;
  applyLoadedState: (nextState: ChatState, search?: string, options?: LoadOptions) => void;
  reload: (search?: string, options?: LoadOptions) => Promise<void>;
};

type Step = { ctx: LoadContext; ticket: number; search: string; options?: LoadOptions };

// Returns true when the session-only refresh handled the load (applied or dropped as superseded).
async function refreshSessionOnly({ ctx, ticket, search, options }: Step): Promise<boolean> {
  const { chatState } = ctx;
  const refreshOf = options?.sessionOnly && chatState ? sessionSwitchTarget(search) : null;
  if (!refreshOf || !chatState || chatState.selectedSession?.id !== refreshOf) return false;
  const view = await readSessionView(refreshOf);
  if (!isLatestStateLoad(ctx.loadSequence, ticket)) {
    return true;
  }
  if (!view || view.requestedSessionNotFound || view.selectedSession?.id !== refreshOf) return false;
  const idle = !view.selectedSessionIsRunning;
  if (idle && (chatState.selectedSessionIsRunning || !threadListed(chatState.activeThreadGroups, refreshOf))) {
    ctx.listRefreshFor.current = refreshOf;
  }
  ctx.applyLoadedState(viewToState(view, chatState), search, options);
  // Until a full bootstrap has applied, every idle view of that chat asks for it again (a later refresh
  // supersedes a bootstrap still running).
  if (idle && ctx.listRefreshFor.current === refreshOf) {
    void ctx.reload(search, { preserveTrace: options?.preserveTrace, silent: true });
  }
  return true;
}

// A switch to an existing chat reads only that session's view; the full bootstrap stays the fallback
// (first load, silent refreshes, other addresses, and servers without the view endpoint).
async function switchSession({ ctx, ticket, search, options }: Step): Promise<boolean> {
  const { chatState } = ctx;
  const switchTo = !options?.silent && chatState ? sessionSwitchTarget(search) : null;
  if (!switchTo || !chatState) return false;
  const view = await readSessionView(switchTo);
  if (!isLatestStateLoad(ctx.loadSequence, ticket)) {
    return true;
  }
  if (!view) return false;
  ctx.applyLoadedState(viewToState(view, chatState), search, options);
  return true;
}

function showLoadError({ ctx, options }: Step, loadError: unknown) {
  if (!options?.silent) {
    ctx.setLoading(false);
  }
  ctx.setSending(false);
  ctx.setPendingPrompt(null);
  // Nothing loaded yet: the app shows BootstrapUnavailable with these words (not an empty shell).
  ctx.setError(
    !ctx.chatState
      ? bootstrapFailureText(loadError)
      : loadError instanceof Error ? loadError.message : "Failed to load chat",
  );
}

export async function loadChatState(ctx: LoadContext, search: string, options?: LoadOptions) {
  const ticket = beginStateLoad(ctx.loadSequence);
  const step: Step = { ctx, ticket, search, options };
  if (!options?.silent) {
    ctx.setLoading(true);
  }
  try {
    if (await refreshSessionOnly(step)) return;
    if (await switchSession(step)) return;
    const nextState = await readJson<ChatState>(chatApiPath(`/bootstrap${search}`));
    if (!isLatestStateLoad(ctx.loadSequence, ticket)) {
      return;
    }
    ctx.listRefreshFor.current = null;
    ctx.applyLoadedState(nextState, search, options);
  } catch (loadError) {
    if (!isLatestStateLoad(ctx.loadSequence, ticket)) {
      return;
    }
    showLoadError(step, loadError);
  }
}
