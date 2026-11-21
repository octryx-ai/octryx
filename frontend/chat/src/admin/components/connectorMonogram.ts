// The neutral fallback for a connector without a brand glyph: a monogram from its name. ServiceNow's entry in
// CONNECTOR_ICONS is a generic stand-in (simple-icons ships no ServiceNow glyph), so it counts as glyph-less too.
const GENERIC_GLYPH_KINDS = new Set(["servicenow"]);

export function hasBrandGlyph(kind: string, glyphs: Record<string, unknown>): boolean {
  return Boolean(glyphs[kind]) && !GENERIC_GLYPH_KINDS.has(kind);
}

/** "ServiceNow" → "SN", "Azure DevOps" → "AD", "servicenow" → "S"; at most two letters. */
export function connectorMonogram(label: string): string {
  const words = label.trim().split(/[\s_\-./]+/).filter(Boolean);
  if (!words.length) return "?";
  if (words.length > 1) return (words[0].charAt(0) + words[1].charAt(0)).toUpperCase();
  const capitals = words[0].match(/[A-Z]/g) ?? [];
  return (capitals.length > 1 ? capitals.slice(0, 2).join("") : words[0].charAt(0)).toUpperCase();
}
