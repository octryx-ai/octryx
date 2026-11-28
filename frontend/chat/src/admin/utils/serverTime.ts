// The server often sends UTC without a zone, which new Date would read as local time.

const NAIVE_ISO = /^(\d{4}-\d{2}-\d{2})[T ](\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?)$/;

export function serverTimeOf(value: string | null | undefined): number | null {
  if (typeof value !== "string" || !value.trim()) return null;
  const text = value.trim();
  const naive = NAIVE_ISO.exec(text);
  const time = Date.parse(naive ? `${naive[1]}T${naive[2]}Z` : text);
  return Number.isFinite(time) ? time : null;
}
