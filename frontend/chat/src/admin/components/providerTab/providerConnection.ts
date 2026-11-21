import { providerAuthLabel } from "./providerAuthLabel";

// One provider connection card on Runtime → Providers: connection and health
// only. Which models are offered, cleared and used lives in the Model catalog. No driver key or id is shown.

export type ConnectionView = {
  initial: string;
  kind: "gateway" | "bedrock" | "other";
  status: string;
  tone: "active" | "neutral" | "attention";
  meta: string;
};

const READINESS_LABELS: Record<string, string> = {
  ready: "Ready", degraded: "Degraded", unknown: "Not checked", unavailable: "Unavailable",
  needs_configuration: "Needs configuration",
};

const KIND_LABELS: Record<ConnectionView["kind"], string> = {
  gateway: "Model gateway", bedrock: "Amazon Bedrock", other: "",
};

function kindOf(provider: Record<string, any>): ConnectionView["kind"] {
  if (provider.driver === "litellm_gateway") return "gateway";
  if (provider.driver === "bedrock_api") return "bedrock";
  return "other";
}

export function connectionView(provider: Record<string, any>): ConnectionView {
  const kind = kindOf(provider);
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
    kind === "bedrock" ? provider.aws_region : "",
    providerAuthLabel(provider),
    `${Number(provider.active_model_count) || 0} of ${Number(provider.model_count) || 0} models enabled`,
  ].filter((part) => typeof part === "string" && part.trim());
  return { initial: name.trim().charAt(0).toUpperCase() || "P", kind, status, tone, meta: parts.join(" · ") };
}
