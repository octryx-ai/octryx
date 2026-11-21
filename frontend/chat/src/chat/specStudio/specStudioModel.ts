// Spec Studio model: the data the backend sends (`/api/v1/workflow-runs/{id}/spec-studio`) and the pure
// rules the page applies to it — the live contrast check, the mock's CSS variables, where a pin sits and what
// approval needs. The backend decides again on every change; this only keeps the page live without a round trip.

export type Tone = "neutral" | "ok" | "warn" | "error" | "accent";
export type Palette = Record<string, string>;
export type Block = {
  type: string; text?: string; title?: string; meta?: string; badge?: string; badge_tone?: string; art?: string;
  icon?: string; variant?: string; go?: string; label?: string; value?: string | number; suffix?: string;
  tone?: string; action?: string; sub?: string; blocks?: Block[];
  items?: { text?: string; label?: string; value?: string; tone?: string }[];
};
export type Screen = {
  id: string; name: string; route: string; nav: string; focus: boolean; filled: Block[]; empty: Block[];
  empty_not_applicable: string; next_step: string; note: string;
};
export type Direction = {
  id: string; name: string; hint: string; light: Palette; dark: Palette;
  fonts: { head: string; body: string; mono: string }; radius: number;
};
export type Question = {
  id: string; question: string; why: string; identifier: string; proposal: string; affects: string[];
  options: { value: string; label: string; detail: string }[];
};
export type Rule = {
  id: string; title: string; text: string; identifier: string; numeric: boolean;
  params: { id: string; label: string; value: string; unit: string }[];
  examples: { given: string; expect: string; realistic: boolean }[];
};
export type Artefact = {
  mode: "new" | "feature"; target: "web" | "flutter"; title: string; summary: string; language: string;
  out_of_scope: string[]; stories: { title: string; summary: string }[];
  design: { proposed: string; directions: Direction[] };
  nav: { id: string; label: string; icon: string; phone: boolean }[];
  screens: Screen[]; questions: Question[]; rules: Rule[]; acceptance: { id: string; text: string }[];
  requirements: { id: string; text: string; zero_config: string; how: string }[];
  glossary: { term: string; translation: string; avoid: string[] }[];
  conditions: { word: string; definition: string }[];
  flow: { progressive_disclosure: string; carry_over: string };
};
export type Comment = {
  id: string; screen: string; device: Device; theme: Theme; data: DataView; x: number; y: number;
  element: string; path: string; text: string; by: string; at: string;
};
export type StudioState = {
  direction?: string; tokens?: Record<string, Palette>; radius?: number; fonts?: Record<string, string>;
  answers?: Record<string, { value?: string; other?: string }>; rules?: Record<string, Record<string, string>>;
  acceptance?: Record<string, { verdict: string; note: string }>; comments?: Comment[];
  reasons?: Record<string, string>;
};
/** The Workspace's Corporate Identity as the run's snapshot: preselected, its values' sources, locks. */
export type Corporate = {
  profile_id: string; profile_name: string; source: "workspace" | "installation"; locks: string[]; hash: string;
  sources: Record<string, "ci" | "derived">; logo: string | null; icons: Record<string, string>; direction: Direction;
};
export type Deviation = { path: string; corporate: string; chosen: string; reason: string };
export type EffectiveDesign = {
  direction: string; name: string; light: Palette; dark: Palette; radius: number;
  fonts: { head: string; body: string; mono: string };
};
export type OpenPoint = { section: string; target: string; text: string; by?: "product_owner" };
export type ApprovedVersion = {
  version: number; who: string; at: string; how: string; decisions: string[]; design?: EffectiveDesign;
  corporate?: { profile_id: string; hash: string }; deviations?: Deviation[];
};
export type StudioPayload = {
  run_id: string; title: string; status: string; awaiting_approval: boolean; payload_hash?: string;
  artefact: Artefact; version: number; base: { screens?: Screen[]; nav?: Artefact["nav"] } | null;
  state: StudioState; design: EffectiveDesign; open_points: OpenPoint[]; needs_revision: boolean; frozen: boolean;
  approved: ApprovedVersion[]; corporate?: Corporate | null; deviations?: Deviation[];
};
export type Device = "desktop" | "phone";
export type Theme = "light" | "dark";
export type DataView = "filled" | "empty";

// The real widths the mock renders at; a smaller viewport scales it down, so a phone sees the whole desktop mock.
export const MOCK_WIDTH: Record<Device, number> = { desktop: 1280, phone: 390 };
export const AA = 4.5;
const DARK_INK = "#1A1410";
const LIGHT_INK = "#FFFFFF";

function luminance(color: string): number {
  const channels = [1, 3, 5].map((index) => parseInt(color.slice(index, index + 2), 16) / 255);
  const linear = channels.map((c) => (c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4));
  return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2];
}

/** WCAG 2.x contrast ratio of two #RRGGBB colours (the same formula as the backend gate). */
export function contrast(foreground: string, background: string): number {
  const a = luminance(foreground);
  const b = luminance(background);
  return (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05);
}

export function onAccent(accent: string): string {
  return contrast(accent, LIGHT_INK) >= contrast(accent, DARK_INK) ? LIGHT_INK : DARK_INK;
}

export const CONTRAST_PAIRS: [string, string, string][] = [
  ["Text on background", "text", "bg"], ["Muted text on card", "muted", "surface"],
  ["Button text on main action", "on_accent", "accent"], ["Warning on card", "warn", "surface"],
  ["OK on card", "ok", "surface"],
];

export type ContrastRow = { theme: Theme; pair: string; ratio: number; passes: boolean };

export function contrastRows(design: EffectiveDesign): ContrastRow[] {
  const rows: ContrastRow[] = [];
  for (const theme of ["light", "dark"] as Theme[]) {
    const palette: Palette = { ...design[theme] };
    if (!palette.accent) continue;
    palette.on_accent = onAccent(palette.accent);
    for (const [pair, fg, bg] of CONTRAST_PAIRS) {
      if (!palette[fg] || !palette[bg]) continue;
      const ratio = contrast(palette[fg], palette[bg]);
      rows.push({ theme, pair, ratio: Math.round(ratio * 100) / 100, passes: ratio >= AA });
    }
  }
  return rows;
}

export const CORPORATE = "corporate";

/** Every direction the product owner can pick: the Corporate Identity first, then the spec's own alternatives. */
export function directionsOf(artefact: Artefact, corporate?: Corporate | null): Direction[] {
  return corporate ? [corporate.direction, ...artefact.design.directions] : artefact.design.directions;
}

/** The direction in use plus the product owner's overrides: what the mock shows before the server answers. */
export function effectiveDesign(artefact: Artefact, state: StudioState, fallback: EffectiveDesign,
  corporate?: Corporate | null): EffectiveDesign {
  const directions = directionsOf(artefact, corporate);
  const chosen = state.direction || (corporate ? CORPORATE : artefact.design.proposed);
  const direction = directions.find((item) => item.id === chosen) ?? directions[0];
  if (!direction) return fallback;
  const tokens = state.tokens ?? {};
  return {
    direction: direction.id, name: direction.name, radius: typeof state.radius === "number" ? state.radius : direction.radius,
    fonts: { ...direction.fonts, ...(state.fonts ?? {}) },
    light: { ...direction.light, ...(tokens.light ?? {}) }, dark: { ...direction.dark, ...(tokens.dark ?? {}) },
  };
}

/** The mock's custom properties for one theme: colours, on-accent, line, fonts and radius (all `--m-*`). */
export function mockVariables(design: EffectiveDesign, theme: Theme): Record<string, string> {
  const palette = design[theme];
  const vars: Record<string, string> = {};
  for (const key of ["bg", "surface", "text", "muted", "accent", "ok", "warn", "error"]) {
    if (palette[key]) vars[`--m-${key}`] = palette[key];
  }
  if (!palette.error) vars["--m-error"] = palette.warn ?? "#B3261E";
  vars["--m-on-accent"] = onAccent(palette.accent ?? "#000000");
  vars["--m-line"] = `color-mix(in srgb, ${palette.text ?? "#000000"} 14%, ${palette.surface ?? "#FFFFFF"})`;
  vars["--m-head"] = design.fonts.head;
  vars["--m-body"] = design.fonts.body;
  vars["--m-mono"] = design.fonts.mono;
  vars["--m-r"] = `${design.radius}px`;
  return vars;
}

/** Fit the mock's real width into the available width: never above 1 (100 %); zoom shows it at 100 %. */
export function mockScale(available: number, device: Device, zoom: boolean): number {
  if (zoom || available <= 0) return 1;
  return Math.min(1, available / MOCK_WIDTH[device]);
}

/** A tap at client (x, y) on the scaled mock, in the mock's own pixels (what a pin stores). */
export function pinPosition(clientX: number, clientY: number, box: { left: number; top: number }, scale: number) {
  return { x: Math.round((clientX - box.left) / scale), y: Math.round((clientY - box.top) / scale) };
}

/** A short name of the tapped element for the comment list: its text, else its kind. */
export function describeElement(text: string, fallback: string): string {
  const clean = text.replace(/\s+/g, " ").trim();
  if (!clean) return fallback;
  return clean.length > 40 ? `${clean.slice(0, 40)}…` : clean;
}

export function screensOf(payload: StudioPayload): Screen[] {
  const own = payload.artefact.screens;
  const base = (payload.base?.screens ?? []).filter((screen) => !own.some((item) => item.id === screen.id));
  return [...own, ...base];
}

export function isContextScreen(payload: StudioPayload, id: string): boolean {
  return !payload.artefact.screens.some((screen) => screen.id === id);
}

export function answerOf(question: Question, state: StudioState): { value: string; other: string } {
  const answer = state.answers?.[question.id];
  return { value: answer?.other ? "" : answer?.value ?? question.proposal, other: answer?.other ?? "" };
}

export type ApproveState = { mode: "approve" | "revise" | "blocked" | "frozen" | "waiting"; reason: string };

/** What the approve button does now: approve, send to revision, or why it cannot. */
export function approveState(payload: StudioPayload): ApproveState {
  if (payload.frozen) return { mode: "frozen", reason: `Version ${payload.approved.length} is approved and frozen.` };
  if (payload.needs_revision) return { mode: "revise", reason: "Your changed values and rejected criteria go back to the spec phase first." };
  const yours = payload.open_points.filter((point) => point.by === "product_owner");
  if (yours.length && yours.length === payload.open_points.length) {
    const count = yours.length;
    return { mode: "blocked", reason: `${count} point${count === 1 ? "" : "s"} for you: give the reason for each deviation from the Corporate Identity (Design).` };
  }
  if (payload.open_points.length) {
    const count = payload.open_points.length;
    return { mode: "blocked", reason: `${count} open point${count === 1 ? "" : "s"} left: the spec phase fixes ${count === 1 ? "it" : "them"} before you approve.` };
  }
  if (!payload.awaiting_approval) return { mode: "waiting", reason: "The spec is still being written or reviewed." };
  return { mode: "approve", reason: "The stories start next; this mock is what every story is reviewed against." };
}

/** How many decisions the product owner made so far (answers, design changes, comments with text). */
export function changeCount(state: StudioState): number {
  const tokens = Object.values(state.tokens ?? {}).reduce((sum, palette) => sum + Object.keys(palette).length, 0);
  return Object.keys(state.answers ?? {}).length + tokens + (state.direction ? 1 : 0) + (typeof state.radius === "number" ? 1 : 0)
    + (state.comments ?? []).filter((comment) => comment.text.trim()).length;
}

export const RADIUS_MAX = 32;

export type ValueMark = { source: "ci" | "derived" | null; locked: boolean };

/** Where a value of the corporate direction comes from and whether the CI locks it (only on that direction). */
export function valueMark(payload: Pick<StudioPayload, "corporate">, design: EffectiveDesign, path: string): ValueMark {
  const corporate = payload.corporate;
  if (!corporate || design.direction !== CORPORATE) return { source: null, locked: false };
  return { source: corporate.sources[path] ?? null, locked: corporate.locks.includes(path) };
}

/** The address of a CI file (logo, icon) of this run's corporate direction. */
export function corporateAssetUrl(runId: string, path: string): string {
  return `/api/v1/workflow-runs/${encodeURIComponent(runId)}/spec-studio/corporate-asset?path=${encodeURIComponent(path)}`;
}

/** A radius the product owner typed: a whole number of px within 0..RADIUS_MAX, or null. */
export function validRadius(input: string | number): number | null {
  const value = typeof input === "number" ? input : Number(input.trim());
  return Number.isInteger(value) && value >= 0 && value <= RADIUS_MAX ? value : null;
}

/** Every element a comment can name on this screen (the keyboard way into comment mode): path and name. */
export function mockElements(artefact: Pick<Artefact, "nav">, screen: Screen, device: Device, data: DataView) {
  const found: { path: string; name: string }[] = [];
  const walk = (blocks: Block[], prefix: string) => blocks.forEach((block, i) => {
    const path = `${prefix}.${i}`;
    found.push({ path, name: block.title || block.text || block.label || block.type });
    walk(block.blocks ?? [], path);
  });
  if (!screen.focus) {
    for (const entry of artefact.nav) {
      if (device === "phone" ? entry.phone !== false : entry.id !== "more") found.push({ path: `nav.${entry.id}`, name: `Navigation: ${entry.label}` });
    }
  }
  walk(data === "empty" && screen.empty.length ? screen.empty : screen.filled, data);
  return found;
}
