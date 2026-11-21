import { formatClock, formatDateTime } from "../../utils/dateTime";
import { serverTimeOf } from "../../utils/serverTime";

// Server timestamps of the Knowledge API read as UTC: a zoneless value is UTC as the server stores it, one with
// `Z` or an offset is read as written. The one rule lives in admin/utils/serverTime.ts.

/** Epoch milliseconds of a server timestamp, or null when it is missing or not a valid time. */
export const apiTimeOf = serverTimeOf;

/** Local date and time of a server timestamp; "—" when it is missing or unreadable. */
export function formatApiTime(value: string | null | undefined): string {
  const time = apiTimeOf(value);
  return formatDateTime(time);
}

/** Local clock time only (the end of a run that started the same day). */
export function formatApiClock(value: string | null | undefined): string {
  const time = apiTimeOf(value);
  return formatClock(time);
}
