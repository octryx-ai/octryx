import { formatClock, formatDateTime, formatExactTime } from "../admin/utils/dateTime";

const ISO_TIMESTAMP_ZONE_PATTERN = /(?:z|[+-]\d{2}:?\d{2})$/i;
const ISO_DATE_TIME_PATTERN = /^\d{4}-\d{2}-\d{2}T/;

export function parseChatTimestamp(value: string | null | undefined) {
  const trimmed = value?.trim();
  if (!trimmed) {
    return null;
  }
  const normalized =
    ISO_DATE_TIME_PATTERN.test(trimmed) &&
    !ISO_TIMESTAMP_ZONE_PATTERN.test(trimmed)
      ? `${trimmed}Z`
      : trimmed;
  const date = new Date(normalized);
  return Number.isNaN(date.getTime()) ? null : date;
}

// Chat times follow the UI's one format (admin/utils/dateTime.ts): "13:31", "7 Oct 2026, 13:31".
export function formatChatTime(value: string | null | undefined, fallback = "") {
  return formatClock(parseChatTimestamp(value), fallback);
}

export function formatChatDateTime(value: string | null | undefined, fallback = "—") {
  return formatExactTime(parseChatTimestamp(value), fallback);
}

export function formatChatShortDateTime(value: string | null | undefined, fallback = "") {
  return formatDateTime(parseChatTimestamp(value), fallback);
}
