// Settings → Security → Content security. Pure: reads
// `/api/v1/admin/content-security` (backend services/content_security/).

import type { EditTarget } from "../policyEngine/policyCatalogModel";

export type CoverageCell = { category: string; outcome: string; text: string; tone: string };
export type CoverageRow = { key: string; label: string; sub: string; cells: CoverageCell[] };
export type Coverage = {
  categories: { id: string; label: string }[]; rows: CoverageRow[]; mode: string; detectors: number; customDetectors: number;
  contentPolicies: number; publishedVersion: number | null; platformPolicies: PlatformPolicy[];
};
/** A shipped platform content policy: enforced on every model call, whatever the driver or the engine mode. */
export type PlatformPolicy = { id: string; label: string; outcome: string };
export type ApprovedModel = { alias: string; clearedUpTo: string; approvedFor: string[]; levels: string[] };
export type ContentSecurity = {
  coverage: Coverage; editTarget: EditTarget | null; approvedModels: ApprovedModel[];
  levels: { key: string; label: string; color: string }[];
};

const isRecord = (value: unknown): value is Record<string, unknown> => typeof value === "object" && value !== null && !Array.isArray(value);
const text = (value: unknown) => (typeof value === "string" ? value : "");
const list = (value: unknown) => (Array.isArray(value) ? value : []);
const strings = (value: unknown) => list(value).map((item) => String(item));
const num = (value: unknown) => (typeof value === "number" ? value : 0);

export function readContentSecurity(payload: unknown): ContentSecurity | null {
  if (!isRecord(payload) || !isRecord(payload.coverage)) return null;
  const coverage = payload.coverage;
  const target = isRecord(payload.edit_target) ? payload.edit_target : null;
  return {
    coverage: {
      categories: list(coverage.categories).filter(isRecord).map((item) => ({ id: text(item.id), label: text(item.label) })),
      rows: list(coverage.rows).filter(isRecord).map((row) => ({
        key: text(row.key), label: text(row.label), sub: text(row.sub),
        cells: list(row.cells).filter(isRecord).map((cell) => ({
          category: text(cell.category), outcome: text(cell.outcome), text: text(cell.text), tone: text(cell.tone),
        })),
      })),
      mode: text(coverage.mode), detectors: num(coverage.detectors), customDetectors: num(coverage.custom_detectors),
      contentPolicies: num(coverage.content_policies),
      publishedVersion: typeof coverage.published_version === "number" ? coverage.published_version : null,
      platformPolicies: list(coverage.platform_policies).filter(isRecord)
        .map((item) => ({ id: text(item.id), label: text(item.label), outcome: text(item.outcome) })),
    },
    editTarget: target && typeof target.version === "number"
      ? { version: target.version, digest: text(target.digest), createsDraft: target.creates_draft === true } : null,
    approvedModels: list(payload.approved_models).filter(isRecord).map((row) => ({
      alias: text(row.alias), clearedUpTo: text(row.cleared_up_to), approvedFor: strings(row.approved_for), levels: strings(row.levels),
    })),
    levels: list(payload.levels).filter(isRecord).map((level) => ({ key: text(level.key), label: text(level.label), color: text(level.color) })),
  };
}

export const CATEGORY_TEXT: Record<string, string> = { prompt_injection: "Prompt injection", pii: "Personal data", secrets: "Secrets" };
