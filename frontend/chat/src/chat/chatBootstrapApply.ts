// Applies a loaded chat state: merges it, asks for the speech config once, and resets the selections and panels.
import type { MutableRefObject } from "react";

import type { ChatState } from "../types";
import { CHAT_API_V1_BASE, readJson } from "./chatApiClient";
import { isExplicitAgentLaunch } from "./agentLaunch";
import { isChatPerformanceDebugEnabled } from "./chatBootstrapReads";
import type { ChatBootstrapStateArgs, LoadOptions } from "./chatBootstrapTypes";
import { mergeBootstrapState } from "./mergeChatState";

export type ApplyContext = ChatBootstrapStateArgs & { ttsRequested: MutableRefObject<boolean> };

function launchFlags(mergedState: ChatState) {
  const nextAgentOption =
    (mergedState.agentOptions ?? []).find(
      (agent) => agent.id === (mergedState.selectedAgentId || ""),
    ) ?? null;
  const isNewThreadState =
    !mergedState.selectedSession && Boolean(mergedState.newThread);
  const hasExplicitLaunchSelection = Boolean(mergedState.selectedAgentId);
  const shouldResetNeutralNewThread =
    isNewThreadState && !hasExplicitLaunchSelection;
  const currentUserIsAdmin = Boolean(
    mergedState.currentUser?.roles?.some(
      (role) => role.trim().toLowerCase() === "admin",
    ),
  );
  return { nextAgentOption, isNewThreadState, shouldResetNeutralNewThread, currentUserIsAdmin };
}

type Flags = ReturnType<typeof launchFlags>;

function requestTtsConfigOnce(ctx: ApplyContext) {
  if (ctx.ttsRequested.current) return;
  ctx.ttsRequested.current = true;
  readJson<{ enabled: boolean }>(`${CHAT_API_V1_BASE}/tts/config`)
    .then((cfg) => ctx.setTtsEnabled(cfg.enabled))
    .catch(() => {
      /* ignore: read aloud stays off */
    });
}

function applyLaunchSelection(ctx: ApplyContext, mergedState: ChatState, flags: Flags, search?: string) {
  const reset = flags.shouldResetNeutralNewThread;
  ctx.setSelectedProjectId(
    mergedState.selectedProjectId ||
      // A new chat starts in the Instance's default workspace when one is set.
      mergedState.projects?.find((project) => project.isDefault)?.id ||
      (flags.currentUserIsAdmin ? "" : mergedState.projects?.[0]?.id || ""),
  );
  ctx.setSelectedRuntimeTargetId(mergedState.selectedRuntimeTargetId || "");
  ctx.setSelectedThinkingLevel(mergedState.selectedThinkingLevel || "light");
  ctx.setSelectedAgentGroupId(reset ? "" : flags.nextAgentOption?.groupId || "");
  ctx.setSelectedAgentId(reset ? "" : mergedState.selectedAgentId || "");
  ctx.setSelectedModeKey(reset ? "diagnosis" : mergedState.selectedAgentType || "diagnosis");
  if (mergedState.selectedSession || reset) {
    ctx.setRoutingOverridesEnabled(false);
  } else if (
    isExplicitAgentLaunch(
      search ?? window.location.search,
      flags.isNewThreadState,
      mergedState.selectedAgentId,
      (mergedState.agentOptions ?? []).map((agent) => agent.id),
    )
  ) {
    // Test exactly this agent.
    ctx.setRoutingOverridesEnabled(true);
  }
}

function closePanels(ctx: ApplyContext, mergedState: ChatState, options?: LoadOptions) {
  ctx.setRenameValue(mergedState.selectedSession?.title || "");
  ctx.setRenameOpen(false);
  ctx.setSidebarOpen(false);
  ctx.setStatsOpen(false);
  ctx.setTaskErrorOpen(false);
  if (!options?.preserveTrace) {
    ctx.setTraceOpen(false);
  }
}

function logApplyTiming(applyStartedAt: number, mergedState: ChatState, options?: LoadOptions) {
  if (!isChatPerformanceDebugEnabled()) return;
  console.info("chat.bootstrap.apply_timing", {
    total_ms: Math.round(performance.now() - applyStartedAt),
    silent: Boolean(options?.silent),
    selected_session_id: mergedState.selectedSession?.id || "",
    selected_session_status: mergedState.selectedSession?.status || "",
    selected_run_status: mergedState.selectedSession?.runStatus || "",
    active_thread_group_count: mergedState.activeThreadGroups?.length || 0,
    selected_message_count: mergedState.selectedMessages?.length || 0,
  });
}

export function applyLoadedChatState(
  ctx: ApplyContext,
  nextState: ChatState,
  search?: string,
  options?: LoadOptions,
) {
  const applyStartedAt = performance.now();
  const mergedState = mergeBootstrapState({ nextState, previousState: ctx.chatState });
  const flags = launchFlags(mergedState);
  ctx.setChatState(mergedState);
  if (flags.currentUserIsAdmin) requestTtsConfigOnce(ctx);
  if (!options?.silent) {
    applyLaunchSelection(ctx, mergedState, flags, search);
    closePanels(ctx, mergedState, options);
  }
  ctx.setError(null);
  ctx.setLoading(false);
  ctx.setSending(false);
  ctx.setPendingPrompt(null);
  if (search !== undefined) {
    window.history.replaceState({}, "", `/chat${search}`);
  }
  logApplyTiming(applyStartedAt, mergedState, options);
}
