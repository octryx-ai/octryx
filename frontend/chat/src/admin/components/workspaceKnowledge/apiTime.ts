import { formatClock, formatDateTime } from "../../utils/dateTime";
import { serverTimeOf } from "../../utils/serverTime";

export const apiTimeOf = serverTimeOf;

export function formatApiTime(value: string | null | undefined): string {
  const time = apiTimeOf(value);
  return formatDateTime(time);
}

export function formatApiClock(value: string | null | undefined): string {
  const time = apiTimeOf(value);
  return formatClock(time);
}
