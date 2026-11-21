import { useEffect, useRef, useState, type MutableRefObject } from "react";

import { buildChatSearch, sanitizeStreamActivityMessage } from "./appHelpers";
import { emitDeviceJobEvent } from "./devices/deviceJobEvents";
import { emitTurnExecutionRefresh } from "./run/turnExecutionRefreshSignal";

const SESSION_STREAM_POLL_INTERVAL_MS = 1500;
const SESSION_STREAM_INACTIVITY_THRESHOLD_MS = 4000;

type LoadStateFn = (
  search?: string,
  options?: { preserveTrace?: boolean; silent?: boolean; sessionOnly?: boolean },
) => Promise<void> | void;

type SessionStreamMessage = {
  type?: string;
  content?: string;
  toolName?: string;
  status?: string;
};

const REFRESH_EVENT_TYPES = new Set([
  "approval_request",
  "run_state",
  "tool_call_end",
]);

function toolActivityLabel(message: SessionStreamMessage): string {
  const toolName = message.toolName || "tool";
  const status = String(message.status || "").toLowerCase();
  if (message.type === "tool_call_begin") {
    return `Running ${toolName}...`;
  }
  if (status === "error" || status === "failed") {
    return `${toolName} failed`;
  }
  return `${toolName} completed`;
}

type StreamContext = {
  sessionSocketRef: MutableRefObject<WebSocket | null>;
  loadStateRef: MutableRefObject<LoadStateFn>;
  lastStreamActivityAtRef: MutableRefObject<number>;
  setSessionStreamConnected: (connected: boolean) => void;
  setStreamActivityMessage: (message: string | null) => void;
};

// Applies one session stream event: device job events, the activity line and the refresh of the session.
function handleStreamEvent(ctx: StreamContext, sessionId: string, event: MessageEvent) {
  try {
    const message = JSON.parse(event.data) as SessionStreamMessage;
    if (message.type === "device_job_event") {
      // The live device job block applies it; a finished or refused turn brings the answer.
      const payload = message as unknown as Record<string, unknown>;
      emitDeviceJobEvent(sessionId, payload);
      if (payload.eventType === "turn_finished" || payload.eventType === "job_rejected") {
        void ctx.loadStateRef.current(buildChatSearch({ sessionId }), {
          preserveTrace: true,
          silent: true,
          sessionOnly: true,
        });
      }
      return;
    }
    if (message.type === "turn_started") {
      ctx.setStreamActivityMessage("Starting turn...");
      return;
    }
    if (message.type === "agent_message" && message.content) {
      ctx.setStreamActivityMessage(
        sanitizeStreamActivityMessage(message.content),
      );
      return;
    }
    if (
      message.type === "tool_call_begin" ||
      message.type === "tool_call_end"
    ) {
      ctx.setStreamActivityMessage(
        sanitizeStreamActivityMessage(toolActivityLabel(message)),
      );
    }
    if (message.type === "tool_call") {
      ctx.setStreamActivityMessage(
        sanitizeStreamActivityMessage(message.content || "Running tool..."),
      );
      return;
    }
    if (message.type && REFRESH_EVENT_TYPES.has(message.type)) {
      if (message.type === "run_state") {
        ctx.setStreamActivityMessage(null);
      }
      if (message.type !== "tool_call_end") {
        emitTurnExecutionRefresh(sessionId);
      }
      const search = buildChatSearch({ sessionId });
      void ctx.loadStateRef.current(search, {
        preserveTrace: true,
        silent: true,
        sessionOnly: true,
      });
    }
  } catch {
    /* ignore malformed websocket events */
  }
}

// Opens the session socket of the selected session; returns the cleanup that closes it.
function openSessionSocket(ctx: StreamContext, sessionId: string, token: string) {
  const protocol = window.location.protocol === "https:" ? "wss" : "ws";
  const socket = new WebSocket(
    `${protocol}://${window.location.host}/api/v1/sessions/${sessionId}/ws?token=${encodeURIComponent(token)}`,
  );
  ctx.sessionSocketRef.current = socket;

  socket.onopen = () => {
    ctx.lastStreamActivityAtRef.current = Date.now();
    ctx.setSessionStreamConnected(true);
  };
  socket.onmessage = (event) => {
    ctx.lastStreamActivityAtRef.current = Date.now();
    handleStreamEvent(ctx, sessionId, event);
  };
  socket.onclose = () => {
    if (ctx.sessionSocketRef.current === socket) {
      ctx.sessionSocketRef.current = null;
    }
    ctx.setSessionStreamConnected(false);
  };
  socket.onerror = () => {
    ctx.setSessionStreamConnected(false);
  };

  return () => {
    if (ctx.sessionSocketRef.current === socket) {
      ctx.sessionSocketRef.current = null;
    }
    socket.close();
  };
}

// Polls a running session while its stream is not connected or has been silent for a while.
function startSessionPolling(
  sessionId: string,
  sessionStreamConnected: boolean,
  lastStreamActivityAtRef: MutableRefObject<number>,
  loadStateRef: MutableRefObject<LoadStateFn>,
) {
  const search = buildChatSearch({ sessionId });
  const intervalId = window.setInterval(() => {
    // Keep long-running sessions visible even when the parent websocket is connected
    // but silent for a while, such as during delegated child-session execution.
    const lastStreamActivityAt = lastStreamActivityAtRef.current;
    const streamIsFresh =
      sessionStreamConnected &&
      lastStreamActivityAt > 0 &&
      Date.now() - lastStreamActivityAt <
        SESSION_STREAM_INACTIVITY_THRESHOLD_MS;
    if (streamIsFresh) {
      return;
    }
    void loadStateRef.current(search, { preserveTrace: true, silent: true, sessionOnly: true });
  }, SESSION_STREAM_POLL_INTERVAL_MS);
  return () => {
    window.clearInterval(intervalId);
  };
}

export function useSessionStream({
  selectedSessionId,
  streamToken,
  selectedSessionIsArchived,
  selectedSessionIsRunning,
  loadState,
}: {
  selectedSessionId: string | null;
  streamToken: string | null;
  selectedSessionIsArchived: boolean;
  selectedSessionIsRunning: boolean;
  loadState: LoadStateFn;
}) {
  const sessionSocketRef = useRef<WebSocket | null>(null);
  const loadStateRef = useRef<LoadStateFn>(loadState);
  const lastStreamActivityAtRef = useRef<number>(0);
  const [sessionStreamConnected, setSessionStreamConnected] = useState(false);
  const [streamActivityMessage, setStreamActivityMessage] = useState<
    string | null
  >(null);

  useEffect(() => {
    loadStateRef.current = loadState;
  }, [loadState]);

  useEffect(() => {
    const current = sessionSocketRef.current;
    if (current) {
      sessionSocketRef.current = null;
      current.close();
    }
    setSessionStreamConnected(false);
    setStreamActivityMessage(null);
    lastStreamActivityAtRef.current = 0;

    if (!selectedSessionId || !streamToken || selectedSessionIsArchived) {
      return;
    }

    return openSessionSocket(
      { sessionSocketRef, loadStateRef, lastStreamActivityAtRef, setSessionStreamConnected, setStreamActivityMessage },
      selectedSessionId,
      streamToken,
    );
  }, [selectedSessionId, selectedSessionIsArchived, streamToken]);

  useEffect(() => {
    if (!selectedSessionId || !selectedSessionIsRunning) {
      return;
    }
    return startSessionPolling(selectedSessionId, sessionStreamConnected, lastStreamActivityAtRef, loadStateRef);
  }, [selectedSessionId, selectedSessionIsRunning, sessionStreamConnected]);

  return {
    streamActivityMessage,
    setStreamActivityMessage,
  };
}
