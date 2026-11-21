import { useCallback, useEffect, useRef, useState } from "react";
import type { Dispatch, MutableRefObject, SetStateAction } from "react";

import type { PluginInstall } from "./pluginsApi";
import { callBridge, decideApproval, loadPluginUi, type Fetcher } from "./pluginUiApi";
import {
  FRAME_MIN_HEIGHT,
  FRAME_REFRESH_MS,
  bridgeContext,
  bridgeRequestError,
  confirmationOf,
  frameLoadError,
  methodAllowed,
  readBridgeOutcome,
  readFrameMessage,
  themeTokens,
  undeclaredError,
  type BridgeError,
  type BridgeOutcome,
  type PluginApproval,
  type PluginUiView,
} from "./pluginUiModel";

export type PluginViewer = { id: string; name: string; role: string };
export type PluginObject = { kind: string; id: string } | null;
export type PluginSlotKind = "page" | "phone" | "tab" | "tile";

type Pending = { id: string; method: string; params: Record<string, unknown>; approval: PluginApproval; error: BridgeError };
type Live = { view: PluginUiView | null; workspaceId: string | null; viewer: PluginViewer; object: PluginObject; slot: { kind: PluginSlotKind; id: string } };
type Install = Pick<PluginInstall, "id" | "name" | "scope">;

function hostTheme(): "light" | "dark" {
  const set = document.documentElement.getAttribute("data-theme");
  if (set === "light" || set === "dark") return set;
  return window.matchMedia?.("(prefers-color-scheme: light)").matches ? "light" : "dark";
}

/** The colour behind the frame: the first ancestor with a background of its own. */
function backgroundBehind(node: HTMLElement | null): string {
  for (let el = node; el; el = el.parentElement) {
    const colour = getComputedStyle(el).backgroundColor;
    if (colour && colour !== "transparent" && !/^rgba\(\s*0,\s*0,\s*0,\s*0\s*\)$/.test(colour)) return colour;
  }
  return getComputedStyle(document.body).backgroundColor;
}

// The frame's state: its /ui view (renewed every FRAME_REFRESH_MS), the height the plugin asked for and the queue
// of calls waiting for the person; `live` holds the latest values for the message handler.
export function usePluginFrameState(fetcher: Fetcher, installId: string, current: Omit<Live, "view">) {
  const frameRef = useRef<HTMLIFrameElement | null>(null);
  const wrapRef = useRef<HTMLDivElement | null>(null);
  const [view, setView] = useState<PluginUiView | null>(null);
  const [failure, setFailure] = useState<{ text: string; title: string } | null>(null);
  const [height, setHeight] = useState(FRAME_MIN_HEIGHT * 4);
  const [pending, setPending] = useState<Pending[]>([]);
  const [deciding, setDeciding] = useState(false);
  const [decideError, setDecideError] = useState<string | null>(null);
  const [generation, setGeneration] = useState(0);

  // The latest values for the message handler (it is registered once per view).
  const live = useRef<Live>({ view, ...current });
  live.current = { view, ...current };

  useEffect(() => {
    let active = true;
    setFailure(null);
    loadPluginUi(fetcher, installId).then(
      (next) => { if (active) setView(next); },
      (error) => { if (active) { setView(null); setFailure(frameLoadError(error)); } },
    );
    const renew = window.setTimeout(() => setGeneration((value) => value + 1), FRAME_REFRESH_MS);
    return () => { active = false; window.clearTimeout(renew); };
  }, [fetcher, installId, generation]);

  return { frameRef, wrapRef, view, failure, height, setHeight, pending, setPending, deciding, setDeciding, decideError, setDecideError, live };
}

type BridgeDeps = {
  frameRef: MutableRefObject<HTMLIFrameElement | null>;
  live: MutableRefObject<Live>;
  sendContext: () => void;
  setHeight: (height: number) => void;
  reply: (id: string, outcome: BridgeOutcome) => void;
  runCall: (method: string, params: Record<string, unknown>) => Promise<BridgeOutcome>;
  setPending: Dispatch<SetStateAction<Pending[]>>;
};

// One message from the frame: ready → context, resize → height, a call → allow-check, run, and either the answer
// or (a write that needs the person) a place in the confirmation queue.
function handleFrameMessage(event: MessageEvent, { frameRef, live, sendContext, setHeight, reply, runCall, setPending }: BridgeDeps) {
  if (!frameRef.current || event.source !== frameRef.current.contentWindow) return;
  const message = readFrameMessage(event.data);
  if (!message) return;
  if (message.kind === "ready") { sendContext(); return; }
  if (message.kind === "resize") { setHeight(message.height); return; }
  if (!methodAllowed(live.current.view, message.method)) { reply(message.id, { error: undeclaredError(message.method) }); return; }
  void runCall(message.method, message.params).then((outcome) => {
    const approval = confirmationOf(outcome);
    if (approval && "error" in outcome) {
      setPending((queue) => [...queue, { id: message.id, method: message.method, params: message.params, approval, error: outcome.error }]);
      return;
    }
    reply(message.id, outcome);
  });
}

// The bridge: context to the frame (again on every theme switch), allow-checked calls and their answers.
export function usePluginBridge(fetcher: Fetcher, install: Install, frame: ReturnType<typeof usePluginFrameState>) {
  const { frameRef, wrapRef, live, setHeight, setPending } = frame;
  const post = useCallback((message: Record<string, unknown>) => {
    frameRef.current?.contentWindow?.postMessage({ v: 1, ...message }, "*");
  }, [frameRef]);

  const sendContext = useCallback(() => {
    const { workspaceId: ws, viewer: who, object: what, slot: where } = live.current;
    const style = getComputedStyle(document.documentElement);
    post({ type: "context", context: {
      workspace_id: ws, user: who, object: what, slot: where,
      theme: { mode: hostTheme(), tokens: themeTokens((name) => style.getPropertyValue(name), backgroundBehind(wrapRef.current)) },
      locale: navigator.language || "en",
    } });
  }, [post, live, wrapRef]);

  const runCall = useCallback(async (method: string, params: Record<string, unknown>): Promise<BridgeOutcome> => {
    try {
      return readBridgeOutcome(await callBridge(fetcher, install.id, { method, params, context: bridgeContext(install.scope, live.current.workspaceId) }));
    } catch (error) {
      return { error: bridgeRequestError(error) };
    }
  }, [fetcher, install.id, install.scope, live]);

  const reply = useCallback((id: string, outcome: BridgeOutcome) => {
    post("error" in outcome ? { id, error: outcome.error } : { id, result: outcome.result });
  }, [post]);

  useEffect(() => {
    const onMessage = (event: MessageEvent) => handleFrameMessage(event, { frameRef, live, sendContext, setHeight, reply, runCall, setPending });
    window.addEventListener("message", onMessage);
    return () => window.removeEventListener("message", onMessage);
  }, [reply, runCall, sendContext, frameRef, live, setHeight, setPending]);

  // The theme follows the host: a switch (data-theme, or the phone's system scheme) resends the context.
  useEffect(() => {
    const observer = new MutationObserver(sendContext);
    observer.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
    const media = window.matchMedia?.("(prefers-color-scheme: light)");
    media?.addEventListener?.("change", sendContext);
    return () => { observer.disconnect(); media?.removeEventListener?.("change", sendContext); };
  }, [sendContext]);

  return { reply, runCall };
}

// Approve (the grant is consumed by the identical call, whose answer goes to the plugin's waiting id) or decline
// (the plugin gets the original error) the first queued call.
export function pluginApprovalActions(fetcher: Fetcher, frame: ReturnType<typeof usePluginFrameState>, bridge: ReturnType<typeof usePluginBridge>) {
  const { pending, setPending, setDeciding, setDecideError } = frame;
  const { reply, runCall } = bridge;
  const current = pending[0] ?? null;
  const finish = (outcome: BridgeOutcome) => {
    if (!current) return;
    reply(current.id, outcome);
    setPending((queue) => queue.slice(1));
    setDecideError(null);
  };
  const approve = async () => {
    if (!current?.approval.approval_id) return;
    setDeciding(true);
    setDecideError(null);
    try {
      await decideApproval(fetcher, current.approval.approval_id, "approve");
    } catch (error) {
      setDecideError(error instanceof Error && error.message ? error.message : "The approval could not be saved.");
      setDeciding(false);
      return;
    }
    // The grant is consumed by the identical call; its answer goes to the plugin's waiting id.
    const again = await runCall(current.method, current.params);
    setDeciding(false);
    finish(again);
  };
  const decline = async () => {
    if (!current) return;
    if (current.approval.approval_id) {
      setDeciding(true);
      await decideApproval(fetcher, current.approval.approval_id, "reject").catch(() => undefined);
      setDeciding(false);
    }
    finish({ error: current.error });
  };
  return { current, approve, decline };
}
