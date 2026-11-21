// `?flow_id=` deep link (admin/editorLinks.ts): on mount the editor opens that workflow through
// its normal authorized load (a failed load shows the editor's usual error). The open workflow stays
// in the address while the editor shows it, so a remount of the admin panel (every panel mount runs
// `loadTab`, which replaces the panel with "Loading…" and mounts it again) or a reload reopens it
// instead of dropping back to the list — the lost first "Open" click. Leaving the editor removes the
// parameter so a reload or a shared URL does not reopen it.
import { useEffect, useRef } from "react";
import { FLOW_ID_PARAM, readFlowIdFromSearch } from "../../editorLinks";

export function urlWithoutFlowId(href: string): string | null {
  try {
    const url = new URL(href);
    if (!url.searchParams.has(FLOW_ID_PARAM)) return null;
    url.searchParams.delete(FLOW_ID_PARAM);
    return `${url.pathname}${url.search}${url.hash}`;
  } catch {
    return null;
  }
}

// The address with `flow_id` set to the open workflow; null when it already says so.
export function urlWithFlowId(href: string, flowId: string): string | null {
  try {
    const url = new URL(href);
    if (url.searchParams.get(FLOW_ID_PARAM) === flowId) return null;
    url.searchParams.set(FLOW_ID_PARAM, flowId);
    return `${url.pathname}${url.search}${url.hash}`;
  } catch {
    return null;
  }
}

// `openFlowId` is the workflow the editor shows, or null while the library list is shown.
export function useFlowDeepLink(openFlow: (flowId: string) => unknown, openFlowId: string | null) {
  const requested = useRef(false);
  const wasOpen = useRef(false);
  useEffect(() => {
    if (requested.current) return;
    requested.current = true;
    const flowId = readFlowIdFromSearch(window.location.search);
    if (flowId) void openFlow(flowId);
    // Read once on mount, like the other editors' deep links.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  useEffect(() => {
    const next = openFlowId
      ? urlWithFlowId(window.location.href, openFlowId)
      : wasOpen.current ? urlWithoutFlowId(window.location.href) : null;
    if (next !== null) window.history.replaceState(window.history.state, "", next);
    wasOpen.current = Boolean(openFlowId);
  }, [openFlowId]);
}
