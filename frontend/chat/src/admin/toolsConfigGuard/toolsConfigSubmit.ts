export type ToolsConfigOutcome = "refused" | "navigate" | "replace_page" | "failed";

export function classifyToolsConfigResponse(status: number, redirected: boolean, contentType: string | null): ToolsConfigOutcome {
  if (status === 409) return "refused";
  if (status >= 200 && status < 300 && redirected) return "navigate";
  if (status >= 200 && status < 300 && (contentType ?? "").includes("text/html")) return "replace_page";
  return "failed";
}

export function failureText(status: number, payload: unknown): string {
  const detail = payload && typeof payload === "object" ? (payload as { detail?: unknown }).detail : null;
  if (typeof detail === "string" && detail.trim()) return `The request failed: ${detail.trim()}`;
  return `The request failed (${status}).`;
}
