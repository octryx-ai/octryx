// One status phrase for a stored health check: words, never a millisecond figure.
// Timing lives only in a check's history.
import { formatRelativeTime } from "./formatters";

export type StoredHealth = {
  status?: string | null;
  error?: string | null;
  last_checked?: string | null;
} | null | undefined;

export type HealthTone = "ok" | "error" | "muted";

export function healthTone(health: StoredHealth): HealthTone {
  const status = (health?.status || "").toLowerCase();
  if (status === "ok") return "ok";
  if (status === "error") return "error";
  return "muted";
}

export function healthPhrase(health: StoredHealth, isActive = true): string {
  if (!isActive) return "Paused";
  const status = (health?.status || "").toLowerCase();
  const checked = formatRelativeTime(health?.last_checked ?? null);
  if (status === "ok") return checked ? `Working · checked ${checked}` : "Working";
  if (status === "error") {
    const cause = (health?.error || "").trim();
    return cause ? `Failing · ${cause}` : "Failing";
  }
  if (status === "no_test") return "No test available";
  return "Not checked yet";
}
