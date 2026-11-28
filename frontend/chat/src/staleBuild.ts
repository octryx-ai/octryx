// After a deploy the old build's lazy chunks are gone: reload once, and leave a second failure to the error boundary instead of looping.

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
