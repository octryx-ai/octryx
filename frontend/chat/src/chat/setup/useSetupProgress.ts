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

// The admin who last saw the setup progress in this browser: the next app start reads their setup status in parallel
// with the bootstrap (startupRequests.ts). Nobody else gets that early read (a 403 for a non-admin).
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

/**
 * "Setup: 3 of 7 done" for admins while a required setup step is open, else null. Read for the
 * Workspace the page shows (`workspaceId`, the one the Workspace switch resolves); refreshed when it changes and
 * when the window gets focus again. Outsider walkthrough: the rail read its own guess of the Workspace
 * (none, when the choice was not stored) and said "2 of 7" while the guide for the shown Workspace said 5 of 7.
 */
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
