import { configOf } from "./connectorConfig";
import type { ConnectorConfig, SourceConnector } from "./connectorTypes";
import type { ReleasesBlock } from "./jiraReleasesContract";

// The editor state of a Jira connector's `releases` block, its shape checks, and the PUT payload.
// The client checks shape only (required, format, duplicates). Bounds and scope membership are the server's: its
// refusal names the field path (releases.products[1], releases.sections[0].title, ...) that `errorsFor` places.
// Rows are sent in draft order and never filtered, so a server path index is the row index shown here.

export type ProductRow = { id: number; projectKey: string; product: string };
export type SectionRow = { id: number; title: string; issueTypes: string[]; labels: string[] };

export type ReleasesDraft = {
  // false: no block (release sync off). The PUT then sends releases: null.
  enabled: boolean;
  products: ProductRow[];
  prefixes: string[];
  sections: SectionRow[];
  blockerPriorities: string[];
};

// Field path -> code. The same paths as the server's refusals.
export type FieldErrors = Record<string, string>;

export type TagField = "releases.version_name_prefixes" | "releases.blocker_priorities" | `releases.sections[${number}].${"issue_types" | "labels"}`;

const PROJECT_KEY = /^[A-Z][A-Z0-9_]{0,49}$/;
const PRODUCT = /^[a-z0-9][a-z0-9-]{0,39}$/;
// eslint-disable-next-line no-control-regex
const CONTROL_CHARS = /[\u0000-\u001f\u007f]/;

let nextRowId = 1;
const rowId = () => nextRowId++;

export function newProductRow(): ProductRow {
  return { id: rowId(), projectKey: "", product: "" };
}

export function newSectionRow(): SectionRow {
  return { id: rowId(), title: "", issueTypes: [], labels: [] };
}

export function draftFromBlock(block: ReleasesBlock | null | undefined): ReleasesDraft {
  return {
    enabled: Boolean(block),
    products: Object.entries(block?.products ?? {}).map(([projectKey, product]) => ({ id: rowId(), projectKey, product })),
    prefixes: [...(block?.version_name_prefixes ?? [])],
    sections: (block?.sections ?? []).map((section) => ({
      id: rowId(),
      title: section.title,
      issueTypes: [...section.issue_types],
      labels: [...section.labels],
    })),
    blockerPriorities: [...(block?.blocker_priorities ?? [])],
  };
}

// The block exactly as it is sent. Prefixes stay as typed ("Release " keeps its space); the rest is trimmed, and
// project and product keys take the case the server stores them in.
export function blockFromDraft(draft: ReleasesDraft): ReleasesBlock | null {
  if (!draft.enabled) return null;
  return {
    products: Object.fromEntries(draft.products.map((row) => [row.projectKey.trim().toUpperCase(), row.product.trim().toLowerCase()])),
    version_name_prefixes: [...draft.prefixes],
    sections: draft.sections.map((row) => ({
      title: row.title.trim(),
      issue_types: row.issueTypes.map((value) => value.trim()),
      labels: row.labels.map((value) => value.trim()),
    })),
    blocker_priorities: draft.blockerPriorities.map((value) => value.trim()),
  };
}

export function isDirty(draft: ReleasesDraft, saved: ReleasesBlock | null | undefined): boolean {
  return JSON.stringify(blockFromDraft(draft)) !== JSON.stringify(blockFromDraft(draftFromBlock(saved)));
}

// Why a tag cannot be added to its list, or null. Prefixes are literal (spaces count); other values match
// case-insensitively on the server, so a case-only duplicate is refused here.
export function tagProblem(field: TagField, value: string, existing: string[]): string | null {
  const literal = field === "releases.version_name_prefixes";
  const candidate = literal ? value : value.trim();
  if (!candidate.trim()) return "client_required";
  if (CONTROL_CHARS.test(candidate)) return "client_invalid_format";
  const same = (other: string) => (literal ? other === candidate : other.trim().toLowerCase() === candidate.toLowerCase());
  return existing.some(same) ? "client_duplicate" : null;
}

// Shape problems that would certainly be refused; an empty object means "send it".
export function checkDraft(draft: ReleasesDraft): FieldErrors {
  const errors: FieldErrors = {};
  if (!draft.enabled) return errors;
  const seen = new Set<string>();
  draft.products.forEach((row, index) => {
    const key = row.projectKey.trim().toUpperCase();
    const product = row.product.trim().toLowerCase();
    const path = `releases.products[${index}]`;
    if (!key || !product) errors[path] = "client_required";
    else if (!PROJECT_KEY.test(key)) errors[path] = "release_project_key_invalid";
    else if (!PRODUCT.test(product)) errors[path] = "release_product_invalid";
    else if (seen.has(key)) errors[path] = "client_duplicate";
    seen.add(key);
  });
  draft.sections.forEach((row, index) => {
    const path = `releases.sections[${index}]`;
    if (!row.title.trim()) errors[`${path}.title`] = "client_required";
    if (!row.issueTypes.length && !row.labels.length) errors[path] = "release_section_without_match";
  });
  return errors;
}

// The errors that belong to one field: its own path and the paths of its items (field[2], field.title, ...).
export function errorsFor(errors: FieldErrors, field: string): [string, string][] {
  return Object.entries(errors).filter(([path]) => path === field || path.startsWith(`${field}[`) || path.startsWith(`${field}.`));
}

// The index of a tag a path points at (releases.blocker_priorities[1] -> 1), or null for the list as a whole.
export function itemIndex(path: string, field: string): number | null {
  const match = path.slice(field.length).match(/^\[(\d+)\]$/);
  return match ? Number(match[1]) : null;
}

// Errors no rendered field shows (the block as a whole, or a path from a newer server): shown above the fields.
export function unplacedErrors(errors: FieldErrors, draft: ReleasesDraft): [string, string][] {
  const placed = [
    ...draft.products.map((_, index) => `releases.products[${index}]`),
    "releases.version_name_prefixes",
    "releases.blocker_priorities",
    "releases.sections",
  ];
  return Object.entries(errors).filter(([path]) => !placed.some((field) => path === field || path.startsWith(`${field}[`)));
}

// The full PUT body: the connector's stored configuration from the listing, with only the block replaced.
// configOf is an allowlist of non-secret fields; a connector stores no credential, and none is ever sent.
export function releasesPayload(connector: SourceConnector, draft: ReleasesDraft): ConnectorConfig {
  return { ...configOf(connector), releases: blockFromDraft(draft) };
}

export function moveRow<T>(rows: T[], index: number, delta: -1 | 1): T[] {
  const target = index + delta;
  if (target < 0 || target >= rows.length) return rows;
  const next = [...rows];
  [next[index], next[target]] = [next[target], next[index]];
  return next;
}
