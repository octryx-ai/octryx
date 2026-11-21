import { useEffect, useState } from "react";

import {
  CHAT_LAYOUT_MEDIA_QUERIES,
  resolveChatLayoutMode,
  type ChatLayoutMode,
} from "./chatLayoutBreakpoints";

// Reports the current chat layout mode. Components use it only to
// decide which chrome is rendered inline and which moves behind a disclosure
// control; the geometry itself stays in CSS media queries so the desktop
// layout is unaffected when JavaScript has not measured yet.

function readLayoutMode(): ChatLayoutMode {
  if (typeof window === "undefined") {
    return "desktop";
  }
  if (typeof window.matchMedia !== "function") {
    return resolveChatLayoutMode(window.innerWidth);
  }
  if (window.matchMedia(CHAT_LAYOUT_MEDIA_QUERIES.phone).matches) {
    return "phone";
  }
  if (window.matchMedia(CHAT_LAYOUT_MEDIA_QUERIES.compact).matches) {
    return "compact";
  }
  return "desktop";
}

export function useChatLayoutMode(): ChatLayoutMode {
  const [mode, setMode] = useState<ChatLayoutMode>(readLayoutMode);

  useEffect(() => {
    if (typeof window === "undefined") {
      return;
    }
    const syncMode = () => setMode(readLayoutMode());
    syncMode();

    if (typeof window.matchMedia !== "function") {
      window.addEventListener("resize", syncMode);
      return () => window.removeEventListener("resize", syncMode);
    }

    const queries = [
      window.matchMedia(CHAT_LAYOUT_MEDIA_QUERIES.phone),
      window.matchMedia(CHAT_LAYOUT_MEDIA_QUERIES.compact),
    ];
    for (const query of queries) {
      query.addEventListener("change", syncMode);
    }
    return () => {
      for (const query of queries) {
        query.removeEventListener("change", syncMode);
      }
    };
  }, []);

  return mode;
}
