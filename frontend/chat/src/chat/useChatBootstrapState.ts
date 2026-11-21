import { useEffect, useRef } from "react";

import type { ChatState } from "../types";
import type { TurnTrace } from "../chatThreadTypes";
import { chatApiPath, readJson } from "./chatApiClient";
import { applyLoadedChatState } from "./chatBootstrapApply";
import { loadChatState } from "./chatBootstrapLoad";
import { createStateLoadSequence, supersedeStateLoads } from "./stateLoadSequence";
import type { ChatBootstrapStateArgs, LoadOptions } from "./chatBootstrapTypes";

export function useChatBootstrapState(args: ChatBootstrapStateArgs) {
  const loadSequence = useRef(createStateLoadSequence()).current;
  // The chat whose turn ended and whose row in the chat list still needs the full bootstrap (sessionOnly refreshes).
  const listRefreshFor = useRef<string | null>(null);
  // Speech (read aloud) is admin-only on the server, its config too: only an admin asks for it, once (no 403 for others).
  const ttsRequested = useRef(false);

  const applyLoadedState = (
    nextState: ChatState,
    search?: string,
    options?: LoadOptions,
  ) => applyLoadedChatState({ ...args, ttsRequested }, nextState, search, options);

  // A state applied from outside a load is newer than every load still running.
  const applyState = (
    nextState: ChatState,
    search?: string,
    options?: LoadOptions,
  ) => {
    supersedeStateLoads(loadSequence);
    applyLoadedState(nextState, search, options);
  };

  function loadState(
    search = window.location.search,
    options?: LoadOptions,
  ): Promise<void> {
    return loadChatState(
      { ...args, loadSequence, listRefreshFor, applyLoadedState, reload: loadState },
      search,
      options,
    );
  }

  const loadTurnTrace = async (traceId: string) => {
    if (!traceId) {
      return null;
    }
      return readJson<TurnTrace>(
      chatApiPath(`/turn-traces/${encodeURIComponent(traceId)}`),
    );
  };

  useEffect(() => {
    void loadState(window.location.search);
    const onPopState = () => {
      void loadState(window.location.search, { preserveTrace: true });
    };
    window.addEventListener("popstate", onPopState);
    return () => {
      window.removeEventListener("popstate", onPopState);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return { applyState, loadState, loadTurnTrace };
}
