export type Choice = "subtree" | "page" | "excluded";
export type SpaceMode = "pages" | "whole";

export type PageNode = { id: string; title: string };

export type PickerState = {
  spaces: string[];
  modes: Record<string, SpaceMode>;
  choices: Record<string, Choice>;
  pages: Record<string, { title: string; space: string; parent: string | null; known: boolean }>;
  kept: Record<string, unknown>[];
};

type Entry = Record<string, unknown>;

const text = (value: unknown): string => (typeof value === "string" ? value.trim() : typeof value === "number" ? String(value) : "");
const same = (left: string, right: string) => left.toLowerCase() === right.toLowerCase();

function entriesOf(draftValue: string | undefined): Entry[] | null {
  const raw = (draftValue ?? "").trim();
  if (!raw) return [];
  try {
    const value = JSON.parse(raw);
    if (!Array.isArray(value)) return null;
    return value.map((item) => (typeof item === "string" ? { id: item, enabled: true } : item))
      .filter((item): item is Entry => Boolean(item) && typeof item === "object");
  } catch {
    return null;
  }
}

export function pickerState(draftValue: string | undefined, spaces: string[]): PickerState | null {
  const entries = entriesOf(draftValue);
  if (entries === null) return null;
  const state: PickerState = { spaces, modes: {}, choices: {}, pages: {}, kept: [] };
  // Nothing stored means every page of the allowed spaces is readable.
  for (const space of spaces) state.modes[space] = entries.length ? "pages" : "whole";
  const shown = (key: string) => spaces.find((space) => same(space, key));
  for (const entry of entries) {
    const space = shown(text(entry.space_key));
    if (!space) {
      state.kept.push(entry);
      continue;
    }
    const excludes = Array.isArray(entry.excludes) ? entry.excludes.map(text).filter(Boolean) : [];
    const id = text(entry.id);
    if (entry.whole_space === true && !id) {
      state.modes[space] = "whole";
    } else if (id) {
      state.choices[id] = entry.enabled === false ? "excluded" : entry.include_children === true ? "subtree" : "page";
      state.pages[id] = { title: text(entry.title) || `Page ${id}`, space, parent: state.pages[id]?.parent ?? null,
        known: false };
    } else {
      state.kept.push(entry);
      continue;
    }
    for (const excluded of excludes) {
      if (!state.choices[excluded]) state.choices[excluded] = "excluded";
      const known = state.pages[excluded];
      state.pages[excluded] = { title: known?.title ?? `Page ${excluded}`, space, parent: known?.parent ?? (id || null),
        known: false };
    }
  }
  return state;
}

export function withLevel(state: PickerState, space: string, parent: string | null, nodes: PageNode[]): PickerState {
  const pages = { ...state.pages };
  for (const node of nodes) pages[node.id] = { title: node.title, space, parent, known: true };
  return { ...state, pages };
}

export function choose(state: PickerState, pageId: string, choice: Choice | null): PickerState {
  const choices = { ...state.choices };
  if (choice === null) delete choices[pageId];
  else choices[pageId] = choice;
  return { ...state, choices };
}

export function setMode(state: PickerState, space: string, mode: SpaceMode): PickerState {
  return { ...state, modes: { ...state.modes, [space]: mode } };
}

function nearestChoice(state: PickerState, pageId: string): string | null {
  const seen = new Set<string>([pageId]);
  let parent = state.pages[pageId]?.parent ?? null;
  while (parent && !seen.has(parent)) {
    if (state.choices[parent]) return parent;
    seen.add(parent);
    parent = state.pages[parent]?.parent ?? null;
  }
  return null;
}

export type Effective = { included: boolean; inherited: boolean };

export function effective(state: PickerState, pageId: string): Effective {
  const own = state.choices[pageId];
  if (own) return { included: own !== "excluded", inherited: false };
  const ancestor = nearestChoice(state, pageId);
  if (ancestor) return { included: state.choices[ancestor] === "subtree", inherited: true };
  return { included: state.modes[state.pages[pageId]?.space ?? ""] === "whole", inherited: true };
}

export function compileRules(state: PickerState): Entry[] {
  const entries: Entry[] = [];
  const excludesOf = new Map<string, string[]>();
  const wholeExcludes = new Map<string, string[]>();
  for (const [pageId, choice] of Object.entries(state.choices)) {
    const page = state.pages[pageId];
    if (!page || !state.spaces.includes(page.space)) continue;
    if (choice !== "excluded") {
      entries.push({ id: pageId, title: page.title, space_key: page.space, enabled: true,
        include_children: choice === "subtree" });
    }
    if (choice === "subtree") continue;
    const ancestor = nearestChoice(state, pageId);
    if (ancestor ? state.choices[ancestor] === "subtree" : state.modes[page.space] === "whole") {
      const bucket = ancestor ? excludesOf : wholeExcludes;
      const key = ancestor ?? page.space;
      bucket.set(key, [...(bucket.get(key) ?? []), pageId]);
    } else if (choice === "excluded" && !ancestor && !page.known) {
      entries.push({ id: pageId, title: page.title, space_key: page.space, enabled: false });
    }
  }
  for (const entry of entries) {
    const excludes = excludesOf.get(String(entry.id));
    if (excludes?.length) entry.excludes = [...excludes].sort();
  }
  for (const space of state.spaces) {
    if (state.modes[space] !== "whole") continue;
    const excludes = wholeExcludes.get(space) ?? [];
    entries.push({ space_key: space, whole_space: true, enabled: true, ...(excludes.length ? { excludes: excludes.sort() } : {}) });
  }
  const plain = state.kept.length === 0 && entries.every((entry) => entry.whole_space === true && !entry.excludes);
  return plain && state.spaces.every((space) => state.modes[space] === "whole") ? [] : [...state.kept, ...entries];
}

// Saving no page rule would make every page readable, so the picker asks instead of applying it silently.
export function nothingChosen(state: PickerState): boolean {
  return compileRules(state).length === 0 && state.spaces.some((space) => state.modes[space] === "pages");
}

export function rulesDraft(state: PickerState): string {
  return JSON.stringify(compileRules(state), null, 2);
}

export function pagesSummary(draftValue: string | undefined): string {
  const entries = entriesOf(draftValue);
  if (entries === null) return "The stored page list cannot be read; correct it under Advanced.";
  if (entries.length === 0) return "No page restriction: every page of the allowed spaces.";
  const subtrees = entries.filter((entry) => entry.include_children === true && entry.enabled !== false).length;
  const single = entries.filter((entry) => text(entry.id) && entry.include_children !== true && entry.enabled !== false).length;
  const whole = entries.filter((entry) => entry.whole_space === true).map((entry) => text(entry.space_key));
  const excluded = entries.reduce((sum, entry) => sum + (Array.isArray(entry.excludes) ? entry.excludes.length : 0), 0)
    + entries.filter((entry) => entry.enabled === false).length;
  const parts = [
    subtrees ? `${subtrees} page${subtrees === 1 ? "" : "s"} with everything below` : "",
    single ? `${single} single page${single === 1 ? "" : "s"}` : "",
    whole.length ? `whole space${whole.length === 1 ? "" : "s"} ${whole.join(", ")}` : "",
    excluded ? `${excluded} excluded branch${excluded === 1 ? "" : "es"}` : "",
  ].filter(Boolean);
  return `Only chosen pages: ${parts.join(", ")}. Pages of other spaces are not readable unless chosen.`;
}
