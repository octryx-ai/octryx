// The Confluence page picker (delivery 5): tri-state choices on a lazily loaded page tree, stored as
// `confluence_allowed_pages` entries the backend decision reads (services/confluence_pages/rules.py).
//
// Per node: "subtree" (the page and all below), "page" (this page only) or "excluded"; a node without a choice
// inherits from its nearest ancestor with one. Per space: "pages" (only chosen pages) or "whole" (the whole space,
// minus excluded branches). Compiling:
// - subtree / page → an own entry {id, title, space_key, enabled: true, include_children};
// - excluded or page below an included subtree (or a whole space) → the page's id in that entry's `excludes`, which
//   cuts the page and everything below it (a "page" choice then grants the page itself through its own entry);
// - a whole space → {space_key, whole_space: true, enabled: true, excludes}.
// Entries of spaces the picker does not show are kept unchanged. When every space is whole and nothing is excluded
// the result is [] (no page rules: the allowed spaces alone decide). A space in "pages" mode without any chosen
// page reads nothing while other entries exist; with no entry at all the spaces decide, so "nothing chosen" is never
// applied silently (see `nothingChosen`: the picker asks for whole spaces or cancel).

export type Choice = "subtree" | "page" | "excluded";
export type SpaceMode = "pages" | "whole";

export type PageNode = { id: string; title: string };

export type PickerState = {
  spaces: string[];
  modes: Record<string, SpaceMode>;
  // Page id → its choice; nodes without an entry inherit.
  choices: Record<string, Choice>;
  // What we know about a page: its title, space and parent (null: a top-level page). `known`: the parent was
  // read from Confluence (a loaded level); otherwise it is unknown or guessed from a stored exclude.
  pages: Record<string, { title: string; space: string; parent: string | null; known: boolean }>;
  // Stored entries the picker does not edit (other spaces, entries without a space), kept as they were.
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

/** The picker state of the stored entries for `spaces`; `null` when the draft is not a list (Advanced only). */
export function pickerState(draftValue: string | undefined, spaces: string[]): PickerState | null {
  const entries = entriesOf(draftValue);
  if (entries === null) return null;
  const state: PickerState = { spaces, modes: {}, choices: {}, pages: {}, kept: [] };
  // Nothing stored: every page of the allowed spaces is readable, i.e. each space is whole.
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
      // A stored exclude lies below its entry; its exact parent is learnt when the tree is opened.
      if (!state.choices[excluded]) state.choices[excluded] = "excluded";
      const known = state.pages[excluded];
      state.pages[excluded] = { title: known?.title ?? `Page ${excluded}`, space, parent: known?.parent ?? (id || null),
        known: false };
    }
  }
  return state;
}

/** Remember a loaded level: titles and parents (the real parent replaces a guessed one). */
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

/** The nearest ancestor of `pageId` with a choice, or null (the space decides). */
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

/** Whether a page is readable with the current choices, and whether that comes from an ancestor or the space. */
export function effective(state: PickerState, pageId: string): Effective {
  const own = state.choices[pageId];
  if (own) return { included: own !== "excluded", inherited: false };
  const ancestor = nearestChoice(state, pageId);
  if (ancestor) return { included: state.choices[ancestor] === "subtree", inherited: true };
  return { included: state.modes[state.pages[pageId]?.space ?? ""] === "whole", inherited: true };
}

/** The stored entries of the picker state (see the module comment). */
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
      // A stored exclusion whose place in the tree is not loaded: kept as the stored entry (the page itself).
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
  // Every space whole, nothing excluded and nothing else stored: no page rules at all (the spaces decide).
  const plain = state.kept.length === 0 && entries.every((entry) => entry.whole_space === true && !entry.excludes);
  return plain && state.spaces.every((space) => state.modes[space] === "whole") ? [] : [...state.kept, ...entries];
}

/** Every space narrowed to pages but no page chosen: saving would leave no page rule, i.e. every page readable.
 * The picker never applies that silently: the admin answers "whole spaces" (the same `[]`, now chosen) or cancels. */
export function nothingChosen(state: PickerState): boolean {
  return compileRules(state).length === 0 && state.spaces.some((space) => state.modes[space] === "pages");
}

export function rulesDraft(state: PickerState): string {
  return JSON.stringify(compileRules(state), null, 2);
}

/** A plain-words summary of the stored page entries for the card. */
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
