// Server timestamps read as UTC. The server stores UTC without a zone (`time_utils.utc_now`) and many
// responses serialize it as written ("2026-10-05T12:13:56"); others add `Z` or an offset. `new Date` would read a
// zoneless value as local time (two hours off in CEST, so "Last checked 2 h ago" right after a test), so a value
// without a zone is taken as UTC; anything else is read as written.

const NAIVE_ISO = /^(\d{4}-\d{2}-\d{2})[T ](\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?)$/;

/** Epoch milliseconds of a server timestamp, or null when it is missing or not a valid time. */
export function serverTimeOf(value: string | null | undefined): number | null {
  if (typeof value !== "string" || !value.trim()) return null;
  const text = value.trim();
  const naive = NAIVE_ISO.exec(text);
  const time = Date.parse(naive ? `${naive[1]}T${naive[2]}Z` : text);
  return Number.isFinite(time) ? time : null;
}
