// After a deploy the old build's lazy chunks are gone, so a tab opened before the deploy fails on its next lazy
// import ("Failed to fetch dynamically imported module"). Vite announces that as `vite:preloadError`; the page then
// reloads once onto the new build. A second failure within RELOAD_GAP_MS is left to the error boundary, which says
// what happened and offers the reload, instead of looping.

const KEY = "octryx.staleBuildReloadAt";
const RELOAD_GAP_MS = 60_000;

export function isStaleBuildError(error: unknown): boolean {
  const text = error instanceof Error ? `${error.name} ${error.message}` : String(error ?? "");
  return /Failed to fetch dynamically imported module|Importing a module script failed|error loading dynamically imported module|ChunkLoadError/i.test(text);
}

export function shouldReload(lastAt: number | null, now: number): boolean {
  return lastAt === null || !Number.isFinite(lastAt) || now - lastAt > RELOAD_GAP_MS;
}

function readLast(): number | null {
  try {
    const value = window.sessionStorage.getItem(KEY);
    return value === null ? null : Number(value);
  } catch {
    return null;
  }
}

/** Reloads onto the new build once; false when it already tried a moment ago. */
export function reloadForNewBuild(): boolean {
  const now = Date.now();
  if (!shouldReload(readLast(), now)) return false;
  try { window.sessionStorage.setItem(KEY, String(now)); } catch { /* storage blocked: reload anyway */ }
  window.location.reload();
  return true;
}

export function installStaleBuildReload(): void {
  window.addEventListener("vite:preloadError", (event) => {
    if (reloadForNewBuild()) event.preventDefault();
  });
}
