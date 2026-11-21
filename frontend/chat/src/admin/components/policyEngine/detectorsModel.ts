// The Detectors tab read model and the custom detector form (backend
// `services/content_detection/custom.py` + `api/routes/policy_engine_detectors.py`). Detectors only find; policies
// decide. Custom detectors live in the policy-set version, so they are saved into the draft like a policy edit.
// The drawer's test text is a per-request preview and is never part of a definition (see `buildDetectorsBody`).

export const CUSTOM_PREFIX = "custom.";
export const MAX_PATTERN_CHARS = 300;
export const MAX_CONTEXT_WORDS = 10;
export const CONTEXT_WINDOW = 32;
export const CHECKS = [["none", "None"], ["mod10", "Mod 10 check digit"], ["mod97", "ISO 7064 mod 97"]] as const;
export const CUSTOM_MASK_STYLES = [["type_token", "Type token"], ["last4", "Keep last 4"], ["full", "Full"]] as const;
const SLUG_RULE = /^[a-z][a-z0-9_]{1,39}$/;

const MASK_LABELS: Record<string, string> = {
  last4: "last 4", type_token: "type token", country_last4: "country + last 4", full: "full",
};

export type DetectorCategory = { id: string; label: string; note: string; builtin: boolean };
export type CustomDetector = {
  id: string;
  label: string;
  category: string;
  pattern: string;
  check: string;
  contextWords: string[];
  maskStyle: string;
  workspaceId: string;
};
export type DetectorRow = {
  id: string;
  label: string;
  category: string;
  method: string;
  confidence: string;
  maskStyles: string[];
  builtin: boolean;
  usedBy: string[];
  custom: CustomDetector | null;
};
export type DetectorCatalog = {
  version: number | null;
  state: string | null;
  digest: string | null;
  categories: DetectorCategory[];
  detectors: DetectorRow[];
};
export type DetectorIssue = { detectorId: string; code: string; message: string };

type Raw = Record<string, unknown>;
const isRecord = (value: unknown): value is Raw => typeof value === "object" && value !== null && !Array.isArray(value);
const str = (value: unknown) => (typeof value === "string" ? value : "");
const strings = (value: unknown) => (Array.isArray(value) ? value.filter((item): item is string => typeof item === "string") : []);
const records = (value: unknown) => (Array.isArray(value) ? value.filter(isRecord) : []);

function readCustom(item: Raw): CustomDetector {
  return {
    id: str(item.id), label: str(item.label), category: str(item.category), pattern: str(item.pattern),
    check: str(item.check) || "none", contextWords: strings(item.context_words), maskStyle: str(item.mask_style) || "type_token",
    workspaceId: str(item.workspace_id),
  };
}

export function readDetectorCatalog(raw: unknown): DetectorCatalog {
  const value = isRecord(raw) ? raw : {};
  return {
    version: typeof value.version === "number" ? value.version : null,
    state: str(value.state) || null,
    digest: str(value.digest) || null,
    categories: records(value.categories).map((item) => ({ id: str(item.id), label: str(item.label) || str(item.id), note: str(item.note), builtin: item.builtin !== false })),
    detectors: records(value.detectors).map((item) => ({
      id: str(item.id), label: str(item.label) || str(item.id), category: str(item.category), method: str(item.method),
      confidence: str(item.confidence), maskStyles: strings(item.mask_styles), builtin: item.builtin !== false,
      usedBy: strings(item.used_by), custom: item.builtin === false ? readCustom(item) : null,
    })),
  };
}

/** `[a-z][a-z0-9_]{1,39}` from free text; "" when nothing usable is left. */
export function slugOf(text: string): string {
  const slug = text.toLowerCase().normalize("NFKD").replace(/[̀-ͯ]/g, "")
    .replace(/[^a-z0-9]+/g, "_").replace(/^[^a-z]+/, "").replace(/_+$/, "").slice(0, 40).replace(/_+$/, "");
  return SLUG_RULE.test(slug) ? slug : "";
}

/** The id follows the name (`custom.<slug>`) until the admin edits it. */
export function detectorIdFor(name: string, currentId: string, idEdited: boolean): string {
  if (idEdited) return currentId;
  const slug = slugOf(name);
  return slug ? `${CUSTOM_PREFIX}${slug}` : "";
}

export const validDetectorId = (id: string) => id.startsWith(CUSTOM_PREFIX) && SLUG_RULE.test(id.slice(CUSTOM_PREFIX.length));
export const validCategoryId = (id: string) => SLUG_RULE.test(id);

/** Derived like the backend: high with a check or context words, else medium. */
export function detectorConfidence(detector: Pick<CustomDetector, "check" | "contextWords">): "high" | "medium" {
  return detector.check !== "none" || detector.contextWords.length > 0 ? "high" : "medium";
}

export function parseContextWords(text: string): string[] {
  return [...new Set(text.split(/[,\n]/).map((item) => item.trim().toLowerCase()).filter(Boolean))];
}

export const maskLabel = (style: string) => MASK_LABELS[style] ?? style;

export function filterDetectors(rows: DetectorRow[], query: string, category: string): DetectorRow[] {
  const needle = query.trim().toLowerCase();
  return rows.filter((row) => (!category || row.category === category)
    && (!needle || [row.id, row.label, row.method, row.category].some((value) => value.toLowerCase().includes(needle))));
}

export function categoryLabel(categories: DetectorCategory[], id: string): string {
  const found = categories.find((item) => item.id === id);
  return found ? `${found.label} (${found.id})` : id;
}

/** "Built-in", or "Custom · <scope> · <state>" for the version that holds it. */
export function sourceLabel(row: DetectorRow, state: string | null, workspaceName: (id: string) => string): string {
  if (row.builtin || !row.custom) return "Built-in";
  const scope = row.custom.workspaceId ? workspaceName(row.custom.workspaceId) : "All Workspaces";
  const stage = state === "draft" ? " · draft" : state === "in_review" ? " · in review" : "";
  return `Custom · ${scope}${stage}`;
}

const definition = (item: CustomDetector) => ({
  id: item.id, label: item.label.trim(), category: item.category, pattern: item.pattern, check: item.check,
  context_words: item.contextWords, mask_style: item.maskStyle, workspace_id: item.workspaceId || null,
});

/** The PUT body: only the definition fields the backend accepts — never a test text. */
export function buildDetectorsBody(detectors: CustomDetector[], categories: DetectorCategory[]) {
  return {
    categories: categories.filter((item) => !item.builtin).map((item) => ({ id: item.id, label: item.label })),
    detectors: detectors.map(definition),
  };
}

/** Replace the detector `originalId` (or add it when new). */
export function upsertDetector(list: CustomDetector[], detector: CustomDetector, originalId: string | null): CustomDetector[] {
  const rest = list.filter((item) => item.id !== (originalId ?? detector.id));
  return [...rest, detector];
}

/** The live test of an unsaved definition: per request, never stored (the backend keeps nothing). */
export function previewBody(detector: CustomDetector, categories: DetectorCategory[], text: string) {
  return {
    text,
    detectors: buildDetectorsBody([detector], categories),
    workspace_id: detector.workspaceId || null,
    mask: [detector.id],
  };
}

export type PreviewResult = { counts: Record<string, number>; maskedText: string; truncated: boolean };

export function readPreview(raw: unknown): PreviewResult {
  const value = isRecord(raw) ? raw : {};
  const counts: Record<string, number> = {};
  if (isRecord(value.counts)) for (const [key, count] of Object.entries(value.counts)) if (typeof count === "number") counts[key] = count;
  return { counts, maskedText: str(value.masked_text), truncated: value.truncated === true };
}

export function readDetectorIssues(error: unknown): DetectorIssue[] {
  const value = isRecord(error) ? error : {};
  return records(value.issues).map((item) => ({ detectorId: str(item.detector_id) || str(item.policy_id), code: str(item.code), message: str(item.message) }));
}

/** What blocks the save, checked before the server does it again. */
export function draftProblem(detector: CustomDetector, others: CustomDetector[], newCategory: { id: string; label: string } | null,
  categories: DetectorCategory[] = []): string | null {
  if (!detector.label.trim()) return "Give the detector a name.";
  if (!validDetectorId(detector.id)) return "The id is custom.<lower-case letters, digits, _>.";
  if (others.some((item) => item.id === detector.id)) return "Another custom detector already has this id.";
  if (newCategory && (!validCategoryId(newCategory.id) || !newCategory.label.trim())) return "Give the new category a name.";
  if (newCategory && categories.some((item) => item.id === newCategory.id)) return "A category with this id already exists; pick it instead.";
  if (!detector.category) return "Pick a category.";
  if (!detector.pattern) return "Write a pattern.";
  if (detector.pattern.length > MAX_PATTERN_CHARS) return `The pattern is longer than ${MAX_PATTERN_CHARS} characters.`;
  if (detector.contextWords.length > MAX_CONTEXT_WORDS) return `At most ${MAX_CONTEXT_WORDS} keywords.`;
  return null;
}

export function emptyDetector(category = ""): CustomDetector {
  return { id: "", label: "", category, pattern: "", check: "none", contextWords: [], maskStyle: "type_token", workspaceId: "" };
}
