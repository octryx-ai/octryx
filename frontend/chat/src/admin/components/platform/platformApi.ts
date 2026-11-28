async function readJson(path: string): Promise<unknown> {
  const response = await fetch(path, { credentials: "same-origin", headers: { Accept: "application/json" } });
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  return response.json();
}

export function loadPlatformHealth(): Promise<unknown> {
  return readJson("/api/v1/health");
}

export function loadClientVersion(): Promise<unknown> {
  return readJson("/octryx-claude/version");
}
