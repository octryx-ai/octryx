import { serverTimeOf } from "./serverTime";

// Never all-numeric: 10/07/2026 reads as 10 July in Switzerland and 7 October in the US.

const LOCALE = "en-GB";
const CLOCK: Intl.DateTimeFormatOptions = { hour: "2-digit", minute: "2-digit", hourCycle: "h23" };
const DATE: Intl.DateTimeFormatOptions = { year: "numeric", month: "short", day: "numeric" };

const MINUTE = 60_000;
const HOUR = 60 * MINUTE;
const DAY = 24 * HOUR;

type TimeInput = string | number | Date | null | undefined;

export function timeOf(value: TimeInput): number | null {
  if (value instanceof Date) return Number.isFinite(value.getTime()) ? value.getTime() : null;
  if (typeof value === "number") return Number.isFinite(value) ? value : null;
  return serverTimeOf(value);
}

function format(value: TimeInput, options: Intl.DateTimeFormatOptions, fallback: string): string {
  const time = timeOf(value);
  if (time === null) return fallback;
  try {
    return new Intl.DateTimeFormat(LOCALE, options).format(new Date(time));
  } catch {
    return fallback;
  }
}

/** `7 Oct 2026, 13:31`. */
export function formatDateTime(value: TimeInput, fallback = "—"): string {
  return format(value, { ...DATE, ...CLOCK }, fallback);
}

/** `7 Oct 2026`. */
export function formatDate(value: TimeInput, fallback = "—"): string {
  return format(value, DATE, fallback);
}

/** `13:31`. */
export function formatClock(value: TimeInput, fallback = "—"): string {
  return format(value, CLOCK, fallback);
}

/** `7 Oct 2026, 13:31:07 CEST`: the exact moment, for tooltips and detail views. */
export function formatExactTime(value: TimeInput, fallback = ""): string {
  return format(value, { ...DATE, ...CLOCK, second: "2-digit", timeZoneName: "short" }, fallback);
}

/** Older than a week the date and time; a future moment (a next run) reads `in 11 min`. */
export function formatRelative(value: TimeInput, fallback = "—", now: number = Date.now()): string {
  const time = timeOf(value);
  if (time === null) return fallback;
  const diff = now - time;
  const ahead = diff < 0;
  const span = Math.abs(diff);
  if (span < MINUTE) return ahead ? "in less than a minute" : "just now";
  if (span < HOUR) {
    const minutes = Math.floor(span / MINUTE);
    return ahead ? `in ${minutes} min` : `${minutes} min ago`;
  }
  if (span < DAY) {
    const hours = Math.floor(span / HOUR);
    return ahead ? `in ${hours} h` : `${hours} h ago`;
  }
  if (!ahead && span < 7 * DAY) {
    return `${Math.floor(span / DAY)} d ago`;
  }
  return formatDateTime(time, fallback);
}

/** Never a mix of relative times and date-times in one column: relative up to 7 days, then the date only. */
export function formatRecent(value: TimeInput, fallback = "—", now: number = Date.now()): string {
  const time = timeOf(value);
  if (time === null) return fallback;
  if (time <= now && now - time < 7 * DAY) return formatRelative(time, fallback, now);
  return formatDate(time, fallback);
}
