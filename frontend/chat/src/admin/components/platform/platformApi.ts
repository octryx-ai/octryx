// Existing endpoints read by Admin › Platform. No new backend routes.

async function readJson(path: string): Promise<unknown> {
  const response = await fetch(path, { credentials: "same-origin", headers: { Accept: "application/json" } });
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  return response.json();
}

/** Signed in: version, status, summary, checks and configuration.security_defaults. */
export function loadPlatformHealth(): Promise<unknown> {
  return readJson("/api/v1/health");
}

/** The octryx-claude client this server hands out (version, package hash, Python requirement). */
export function loadClientVersion(): Promise<unknown> {
  return readJson("/octryx-claude/version");
}
