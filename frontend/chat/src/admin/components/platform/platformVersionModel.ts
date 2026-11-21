// Admin › Platform › Version: what runs here, read from existing endpoints only:
// GET /api/v1/health (signed in: version, status, summary, configuration.security_defaults) and
// GET /octryx-claude/version (the agent client this server hands out). Pure reading, shared with the tests.

export type PlatformVersion = {
  server: { version: string; status: string; attention: string[] };
  security: {
    status: string;
    runtimeProfile: string;
    productionLike: boolean;
    debug: boolean;
    secureCookies: boolean;
    forwardedHeaderTrust: string;
  } | null;
};

export type ClientVersion = { version: string; requiresPython: string; sha256: string } | null;

const str = (value: unknown, fallback = ""): string => (typeof value === "string" && value ? value : fallback);
const rec = (value: unknown): Record<string, unknown> => (value && typeof value === "object" ? value as Record<string, unknown> : {});
const list = (value: unknown): string[] => (Array.isArray(value) ? value.filter((v): v is string => typeof v === "string") : []);

export function readPlatformVersion(raw: unknown): PlatformVersion {
  const body = rec(raw);
  const summary = rec(body.summary);
  const security = rec(rec(body.configuration).security_defaults);
  const attention = Array.from(new Set(list(summary.error_components).concat(list(summary.degraded_components),
    list(summary.unknown_components)))).sort();
  return {
    server: { version: str(body.version, "unknown"), status: str(body.status || summary.status, "unknown"), attention },
    security: Object.keys(security).length ? {
      status: str(security.status, "unknown"),
      runtimeProfile: str(security.runtime_profile, "—"),
      productionLike: security.production_like === true,
      debug: security.debug === true,
      secureCookies: security.force_secure_auth_cookies === true,
      forwardedHeaderTrust: str(security.forwarded_header_trust, "—"),
    } : null,
  };
}

export function readClientVersion(raw: unknown): ClientVersion {
  const body = rec(raw);
  const version = str(body.version);
  return version ? { version, requiresPython: str(body.requires_python, "—"), sha256: str(body.sha256) } : null;
}

/** User words for the health roll-up and the security defaults; colour only for exceptions. */
export function serverStateLabel(status: string): { label: string; tone: "neutral" | "attention" | "problem" } {
  if (status === "ok") return { label: "Running", tone: "neutral" };
  if (status === "degraded") return { label: "Needs attention", tone: "attention" };
  if (status === "error") return { label: "Failed", tone: "problem" };
  return { label: "Unknown", tone: "attention" };
}

export function securityLabel(status: string): { label: string; tone: "neutral" | "attention" | "problem" } {
  if (status === "secure") return { label: "Secure defaults", tone: "neutral" };
  if (status === "local_only_defaults") return { label: "Local-only defaults", tone: "attention" };
  if (status === "blocked_by_startup_validation") return { label: "Blocked", tone: "problem" };
  return { label: "Unknown", tone: "attention" };
}

/** "3 components need attention" for the link to Operations › Health; empty when none does. */
export function attentionText(components: string[]): string {
  if (!components.length) return "";
  return components.length === 1 ? "1 component needs attention." : `${components.length} components need attention.`;
}

// How forwarded headers are trusted (backend config.py forwarded_header_trust), in words.
const FORWARDED_TRUST: Record<string, string> = {
  explicit_allowlist: "Only from the listed proxies",
  disabled: "Not trusted",
};

export function forwardedTrustLabel(value: string): string {
  if (FORWARDED_TRUST[value]) return FORWARDED_TRUST[value];
  const words = value.replace(/_/g, " ").trim();
  return words && words !== "—" ? words.charAt(0).toUpperCase() + words.slice(1) : "—";
}

/** The client's requirement and checksum in words: "Python 3.11 or newer · checksum 2262fe507ed8". */
export function clientDetails(client: { requiresPython: string; sha256: string }): string {
  const spec = client.requiresPython.trim();
  const minimum = /^>=\s*([\d.]+)$/.exec(spec);
  const python = !spec || spec === "—" ? "" : minimum ? `Python ${minimum[1]} or newer` : `Python ${spec}`;
  return [python, client.sha256 ? `checksum ${client.sha256.slice(0, 12)}` : ""].filter(Boolean).join(" · ");
}
