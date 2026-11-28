import { useEffect, useState } from "react";

import { loadSetupStatus } from "./setupGuideApi";
import { applySkips, readSkips, setupProgressText, setupSummary } from "./setupGuideModel";

function browserStore(): Storage | null {
  try {
    return window.localStorage;
  } catch {
    return null;
  }
}

// Only the admin who last saw the progress here gets the early read with the bootstrap; anyone else would get a 403.
const SETUP_VIEWER_KEY = "octryx-setup-progress-viewer";

export function readSetupViewer(): string {
  try {
    return browserStore()?.getItem(SETUP_VIEWER_KEY) || "";
  } catch {
    return "";
  }
}

function rememberSetupViewer(userId: string | null | undefined, isAdmin: boolean): void {
  try {
    const store = browserStore();
    if (!store) return;
    if (isAdmin && userId) store.setItem(SETUP_VIEWER_KEY, userId);
    else if (userId) store.removeItem(SETUP_VIEWER_KEY);
  } catch {
    // Storage blocked: the setup status is then read after the bootstrap.
  }
}

/** Reads the Workspace the page shows, never a guess of its own, so the rail and the setup guide agree. */
export function useSetupProgress(isAdmin: boolean, userId: string | null | undefined,
  workspaceId: string | null): string | null {
  const [text, setText] = useState<string | null>(null);
  useEffect(() => {
    rememberSetupViewer(userId, isAdmin);
    if (!isAdmin) {
      setText(null);
      return undefined;
    }
    let current = true;
    const load = () => {
      loadSetupStatus(workspaceId || null)
        .then((status) => {
          if (!current) return;
          setText(status ? setupProgressText(setupSummary(applySkips(status.steps, readSkips(browserStore(), userId)))) : null);
        })
        .catch(() => { if (current) setText(null); });
    };
    load();
    window.addEventListener("focus", load);
    return () => { current = false; window.removeEventListener("focus", load); };
  }, [isAdmin, userId, workspaceId]);
  return text;
}
