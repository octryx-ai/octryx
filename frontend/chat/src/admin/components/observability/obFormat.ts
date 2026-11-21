import { formatRelative } from "../../utils/dateTime";

// Formatting shared by the Observability pages. Unknown is a dash, never 0.

export function formatTime(value: string | null | undefined): string {
  // Relative ("2 min ago"), the date and time after a week; zone-less server times are UTC.
  return formatRelative(value, "–");
}

// Unknown is not zero: a run without a measured start shows "–" (not measured).
export function formatDuration(ms: number | null | undefined): string {
  if (ms === null || ms === undefined) return "–";
  if (ms < 1000) return `${ms} ms`;
  const seconds = ms / 1000;
  if (seconds < 60) return `${seconds.toFixed(seconds < 10 ? 1 : 0)} s`;
  const minutes = Math.floor(seconds / 60);
  return `${minutes} min ${String(Math.round(seconds % 60)).padStart(2, "0")} s`;
}

export function formatMoney(value: number | null | undefined): string {
  if (value === null || value === undefined) return "–";
  return value >= 100
    ? `$${Math.round(value).toLocaleString()}`
    : `$${value.toFixed(2)}`;
}

export function formatCount(value: number | null | undefined): string {
  if (value === null || value === undefined) return "–";
  if (value >= 1_000_000) return `${(value / 1_000_000).toFixed(1)} M`;
  if (value >= 10_000) return `${(value / 1000).toFixed(1)} k`;
  return value.toLocaleString();
}

export function readErrorMessage(error: unknown, fallback: string): string {
  return error instanceof Error && error.message ? error.message : fallback;
}
