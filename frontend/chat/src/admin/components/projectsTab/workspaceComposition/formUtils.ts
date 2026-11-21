export function formatJsonRecord(
  value: Record<string, unknown> | null | undefined,
): string {
  return JSON.stringify(value || {}, null, 2);
}

export function parseJsonRecord(
  text: string,
  label: string,
): Record<string, unknown> {
  const trimmed = text.trim();
  if (!trimmed) {
    return {};
  }
  let parsed: unknown;
  try {
    parsed = JSON.parse(trimmed);
  } catch {
    throw new Error(`${label} must be valid JSON.`);
  }
  if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
    throw new Error(`${label} must be a JSON object.`);
  }
  return parsed as Record<string, unknown>;
}

export function formatStringList(value: string[] | null | undefined): string {
  return Array.isArray(value) ? value.join("\n") : "";
}

export function parseStringList(text: string): string[] {
  return text
    .split(/\r?\n|,/)
    .map((item) => item.trim())
    .filter(Boolean);
}
