// Classification level catalog: reading levels, new level keys, positions, checks and retire refusals.
import type { Rules } from "./classificationPolicyModel";
import { cellDisplay, cellValue, type MatrixRow } from "./classificationMatrixRows";
import { isRecord, list, text } from "./classificationValueReaders";

// ---- level catalog ------------------------------------------------------------------------------

export type CatalogLevel = {
  key: string;
  rank: number;
  label: string;
  color: string;
  description: string;
  models_allowed: boolean;
  builtin: boolean;
};

export const LEVEL_KEY_PATTERN = /^[a-z][a-z0-9_]{1,29}$/;

export function readCatalog(value: unknown): CatalogLevel[] | null {
  if (!Array.isArray(value)) return null;
  const levels = value.filter(isRecord).filter((item) => typeof item.key === "string" && typeof item.rank === "number")
    .map((item) => ({
      key: String(item.key), rank: Number(item.rank), label: text(item.label) || String(item.key), color: text(item.color) || "custom",
      description: text(item.description), models_allowed: item.models_allowed !== false, builtin: item.builtin === true,
    }));
  return levels.sort((a, b) => a.rank - b.rank);
}

/** The level key a name suggests (immutable once saved): lower case, digits and underscores, starts with a letter. */
export function levelKeyFrom(name: string): string {
  const slug = name.toLowerCase().trim().replace(/[^a-z0-9]+/g, "_").replace(/^_+|_+$/g, "");
  return (/^[a-z]/.test(slug) ? slug : slug ? `l_${slug}` : "").slice(0, 30);
}

/** Where a new level can go: after level `index` (between it and the next one, or at the end). */
export function positionOptions(catalog: CatalogLevel[]): { index: number; text: string }[] {
  return catalog.map((level, index) => ({
    index,
    text: catalog[index + 1] ? `Between ${level.label} and ${catalog[index + 1].label}` : `After ${level.label}`,
  }));
}

/** A free rank after position `index`, or null when no whole number fits between the neighbours. */
export function rankAfter(catalog: CatalogLevel[], index: number): number | null {
  const lower = catalog[index];
  const upper = catalog[index + 1];
  if (!lower) return null;
  if (!upper) return lower.rank + 100;
  const middle = Math.floor((lower.rank + upper.rank) / 2);
  return middle > lower.rank && middle < upper.rank ? middle : null;
}

export type LevelCheck = { state: "ok" | "bad" | "info"; text: string };

export function newLevelChecks(catalog: CatalogLevel[], key: string, label: string, index: number): LevelCheck[] {
  const rank = rankAfter(catalog, index);
  const lower = catalog[index];
  const upper = catalog[index + 1];
  const valid = LEVEL_KEY_PATTERN.test(key);
  const unique = !catalog.some((level) => level.key === key);
  return [
    { state: label.trim() ? "ok" : "bad", text: label.trim() ? "The level has a name" : "Enter a name" },
    { state: valid ? "ok" : "bad", text: valid ? `Key ${key} is valid` : "The key must start with a letter: a–z, 0–9, _ (2–30)" },
    { state: unique ? "ok" : "bad", text: unique ? "The key is unique" : `A level with the key ${key} already exists` },
    rank === null
      ? { state: "bad", text: "No free rank between these two levels" }
      : { state: "ok", text: upper ? `Rank ${rank} sits between ${lower.label} (${lower.rank}) and ${upper.label} (${upper.rank}); existing ranks do not move`
        : `Rank ${rank} comes after ${lower?.label} (${lower?.rank})` },
    { state: "info", text: "No Workspace uses this level yet; it can be retired until one does" },
  ];
}

/** The rows whose value at a level restricts something (they generate a policy). */
export function restrictingRows(rows: MatrixRow[], rules: Rules | undefined): MatrixRow[] {
  return rows.filter((row) => !row.derived && !row.notEnforced && ["no", "part"].includes(cellDisplay(row, cellValue(row, rules)).tone));
}

const REFERENCE_KIND: Record<string, string> = {
  workspace: "Workspace", default_level: "Level for new Workspaces", model: "Model", custom_policy: "Custom policy", test_case: "Test case",
};

/** A refused retire, with what still uses the level. */
export function levelInUseText(error: unknown): string | null {
  const record = isRecord(error) ? error : null;
  if (record?.code !== "classification_level_in_use") return null;
  const detail = isRecord(record.detail) ? record.detail : record;
  const references = list(detail.references).filter(isRecord)
    .map((item) => `${REFERENCE_KIND[text(item.kind)] ?? text(item.kind)} ${text(item.name)}`);
  return `The level is still in use${references.length ? `: ${references.join(", ")}` : ""}. Move these to another level first.`;
}
