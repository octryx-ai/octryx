// One provider connection on Models › Providers: connection and health only. Which models are offered,
// cleared and used lives in the Model catalog. No driver key or id is shown.

export type ConnectionView = {
  initial: string;
  kind: "gateway" | "other";
  status: string;
  tone: "active" | "neutral" | "attention";
  meta: string;
};

const READINESS_LABELS: Record<string, string> = {
  ready: "Ready", degraded: "Degraded", unknown: "Not checked", unavailable: "Unavailable",
  needs_configuration: "Needs configuration",
};

const KIND_LABELS: Record<ConnectionView["kind"], string> = {
  gateway: "Model gateway", other: "",
};

export function connectionView(provider: Record<string, any>): ConnectionView {
  const kind: ConnectionView["kind"] = provider.driver === "litellm_gateway" ? "gateway" : "other";
  const name = String(provider.display_name || KIND_LABELS[kind] || "Provider");
  const readiness = String(provider.readiness?.status ?? provider.readiness_status ?? "");
  let status = READINESS_LABELS[readiness] ?? "Not checked";
  let tone: ConnectionView["tone"] = readiness === "ready" ? "active" : readiness === "unknown" || !readiness ? "neutral" : "attention";
  if (!provider.is_active) {
    status = "Disabled";
    tone = "neutral";
  }
  const parts = [
    KIND_LABELS[kind],
    provider.has_api_key ? "Key configured" : "No key",
    `${Number(provider.active_model_count) || 0} of ${Number(provider.model_count) || 0} models enabled`,
  ].filter((part) => part.trim());
  return { initial: name.trim().charAt(0).toUpperCase() || "P", kind, status, tone, meta: parts.join(" · ") };
}
