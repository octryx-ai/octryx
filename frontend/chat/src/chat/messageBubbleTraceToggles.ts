// Trace, thinking and performance toggles of one message bubble, loading the turn trace on first use.
import type { Dispatch, SetStateAction } from "react";

import type { ChatMessage, TurnTrace } from "../chatThreadTypes";
import { extractPerformanceSections, extractThinkingFromTrace } from "./messageBubbleHelpers";

type SetState<T> = Dispatch<SetStateAction<T>>;

export interface TurnTraceToggleState {
  message: ChatMessage;
  onLoadTurnTrace?: (traceId: string) => Promise<TurnTrace | null>;
  effectiveTurnTrace: TurnTrace | null;
  hasTurnTrace: boolean;
  thinkingText: string;
  performance: ReturnType<typeof extractPerformanceSections>;
  traceLoading: boolean;
  setTraceOpen: SetState<boolean>;
  setTraceLoading: SetState<boolean>;
  setLoadedTurnTrace: SetState<TurnTrace | null>;
  thinkingLoading: boolean;
  setThinkingOpen: SetState<boolean>;
  setThinkingLoading: SetState<boolean>;
  setThinkingUnavailable: SetState<boolean>;
  performanceLoading: boolean;
  setPerformanceOpen: SetState<boolean>;
  setPerformanceLoading: SetState<boolean>;
  setPerformanceUnavailable: SetState<boolean>;
}

function traceOpener(state: TurnTraceToggleState) {
  const {
    message, onLoadTurnTrace, effectiveTurnTrace, hasTurnTrace, traceLoading, setTraceOpen, setTraceLoading, setLoadedTurnTrace,
    
  } = state;

  async function openTrace() {
    if (traceLoading || !hasTurnTrace) {
      return;
    }
    if (!effectiveTurnTrace && message.turnTraceId && onLoadTurnTrace) {
      setTraceLoading(true);
      try {
        const trace = await onLoadTurnTrace(message.turnTraceId);
        if (trace) {
          setLoadedTurnTrace(trace);
        }
      } finally {
        setTraceLoading(false);
      }
    }
    setTraceOpen(true);
  }
  return openTrace;
}

function thinkingToggle(state: TurnTraceToggleState) {
  const {
    message, onLoadTurnTrace, effectiveTurnTrace, hasTurnTrace, thinkingText, setLoadedTurnTrace,
    thinkingLoading, setThinkingOpen, setThinkingLoading, setThinkingUnavailable,
  } = state;

  async function toggleThinking() {
    if (thinkingLoading || !hasTurnTrace) {
      return;
    }
    if (thinkingText) {
      setThinkingOpen((value) => !value);
      return;
    }
    if (!effectiveTurnTrace && message.turnTraceId && onLoadTurnTrace) {
      setThinkingLoading(true);
      try {
        const trace = await onLoadTurnTrace(message.turnTraceId);
        if (trace) {
          setLoadedTurnTrace(trace);
          const nextThinking = extractThinkingFromTrace(trace);
          setThinkingUnavailable(!nextThinking);
          setThinkingOpen(Boolean(nextThinking));
          return;
        }
      } finally {
        setThinkingLoading(false);
      }
    }
    setThinkingUnavailable(true);
    setThinkingOpen(false);
  }
  return toggleThinking;
}

function performanceToggle(state: TurnTraceToggleState) {
  const {
    message, onLoadTurnTrace, effectiveTurnTrace, hasTurnTrace, performance, setLoadedTurnTrace,
    performanceLoading, setPerformanceOpen, setPerformanceLoading, setPerformanceUnavailable,
  } = state;

  async function togglePerformance() {
    if (performanceLoading) {
      return;
    }
    if (performance.hasPerformance) {
      setPerformanceOpen((value) => !value);
      return;
    }
    if (!hasTurnTrace) {
      setPerformanceUnavailable(true);
      setPerformanceOpen(false);
      return;
    }
    if (!effectiveTurnTrace && message.turnTraceId && onLoadTurnTrace) {
      setPerformanceLoading(true);
      try {
        const trace = await onLoadTurnTrace(message.turnTraceId);
        if (trace) {
          setLoadedTurnTrace(trace);
          const nextPerformance = extractPerformanceSections(
            trace,
            message.toolEvents,
          );
          setPerformanceUnavailable(!nextPerformance.hasPerformance);
          setPerformanceOpen(nextPerformance.hasPerformance);
          return;
        }
      } finally {
        setPerformanceLoading(false);
      }
    }
    setPerformanceUnavailable(true);
    setPerformanceOpen(false);
  }
  return togglePerformance;
}

export function turnTraceToggles(state: TurnTraceToggleState) {
  return {
    openTrace: traceOpener(state),
    toggleThinking: thinkingToggle(state),
    togglePerformance: performanceToggle(state),
  };
}
