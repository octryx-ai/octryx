// Readable "what this preset needs" line for the MCP catalog.
// Only the preset's own field metadata is used; nothing is inferred from names.

type CatalogFieldLike = {
  name: string;
  label?: string | null;
  type?: string | null;
  required?: boolean | null;
};

type CatalogPresetLike = { fields?: CatalogFieldLike[] | null };

function fieldLabel(field: CatalogFieldLike): string {
  const label = String(field.label || "").trim() || field.name;
  return String(field.type || "").trim().toLowerCase() === "password"
    ? `${label} (secret reference)`
    : label;
}

export function mcpCatalogRequirements(preset: CatalogPresetLike): string {
  const fields = preset.fields || [];
  const required = fields.filter((field) => field.required);
  const optional = fields.length - required.length;
  if (fields.length === 0) return "No configuration";
  const parts: string[] = [];
  if (required.length > 0) parts.push(required.map(fieldLabel).join(", "));
  if (optional > 0) parts.push(`${optional} optional setting${optional === 1 ? "" : "s"}`);
  return required.length > 0 ? parts.join(" · ") : `No required settings · ${parts[0]}`;
}
