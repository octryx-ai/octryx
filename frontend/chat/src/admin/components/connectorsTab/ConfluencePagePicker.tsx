import { type Dispatch, type SetStateAction, useEffect, useState } from "react";
import { ConfluencePageTreeNode } from "./ConfluencePageTreeNode";
import { choose, nothingChosen, pickerState, rulesDraft, setMode, withLevel } from "./confluencePagePickerModel";
import type { Choice, PickerState, SpaceMode } from "./confluencePagePickerModel";
import { levelError, levelKey, PAGE_TREE_URL, readLevel } from "./confluencePageTreeApi";
import type { Level, ReadJson } from "./confluencePageTreeApi";
import "./confluencePagePicker.css";

type Props = {
  spaces: string[];
  draftValue: string | undefined;
  readJson: ReadJson;
  // The tree endpoint of the scope (global or a Workspace); each space is read with the connection serving it.
  treeUrl?: string;
  // Space → the named connection that serves it (absent: the default connection).
  servedBy?: Record<string, string>;
  onApply: (draftValue: string) => void;
  onClose: () => void;
};

type PickerSpaceProps = {
  space: string;
  state: PickerState;
  levels: Record<string, Level>;
  open: Record<string, boolean>;
  servedBy: Record<string, string>;
  setState: (state: PickerState) => void;
  toggle: (space: string, parent: string | null) => void;
  more: (space: string, parent: string | null) => void;
  onChoose: (pageId: string, choice: Choice | null) => void;
};

// One allowed space: its mode (whole space or chosen pages) and, when open, its lazily loaded top level.
function PickerSpace({ space, state, levels, open, servedBy, setState, toggle, more, onChoose }: PickerSpaceProps) {
  const rootKey = levelKey(space, null);
  const root = levels[rootKey];
  return (
    <section className="page-picker__space" data-space={space}>
      <div className="page-picker__space-head">
        <button type="button" className="page-picker__toggle" aria-expanded={Boolean(open[rootKey])}
          aria-label={`${open[rootKey] ? "Close" : "Open"} space ${space}`} onClick={() => toggle(space, null)}>
          {open[rootKey] ? "▾" : "▸"}
        </button>
        <code>{space}</code>
        {servedBy[space] ? <span className="admin-panel__hint">via {servedBy[space]}</span> : null}
        {(["whole", "pages"] as SpaceMode[]).map((mode) => (
          <label key={mode} className="page-picker__mode">
            <input type="radio" name={`page-picker-mode-${space}`} value={mode} checked={state.modes[space] === mode}
              onChange={() => setState(setMode(state, space, mode))} />
            {mode === "whole" ? "Whole space" : "Only chosen pages"}
          </label>
        ))}
      </div>
      {open[rootKey] ? (
        <div className="page-picker__children">
          {root?.error ? <p className="security-field-hint security-field-hint--error" role="alert">{root.error}</p> : null}
          {root?.pages.length ? (
            <ul className="page-picker__list">
              {root.pages.map((node) => (
                <ConfluencePageTreeNode key={node.id} space={space} node={node} state={state} levels={levels}
                  open={open} onToggle={toggle} onMore={more} onChoose={onChoose} />
              ))}
            </ul>
          ) : root && !root.loading && !root.error ? <p className="admin-panel__hint">No pages in this space.</p> : null}
          {root?.loading ? <p className="admin-panel__hint">Loading…</p> : null}
          {root?.nextStart !== null && root?.nextStart !== undefined && !root.loading ? (
            <button type="button" className="admin-panel__action-btn" onClick={() => more(space, null)}>More pages</button>
          ) : null}
        </div>
      ) : null}
    </section>
  );
}

function PickerConfirm({ state, setConfirming, onApply }: {
  state: PickerState;
  setConfirming: (confirming: boolean) => void;
  onApply: (draftValue: string) => void;
}) {
  return (
    <div className="page-picker__confirm" role="alertdialog" aria-label="No page is chosen">
      <p className="security-field-hint security-field-hint--attention">
        No page is chosen. Without a page restriction every page of the allowed spaces is readable. Make the whole
        spaces readable, or cancel and choose pages?
      </p>
      <div className="connector-card__actions">
        <button type="button" className="admin-panel__action-btn admin-panel__action-btn--primary"
          onClick={() => { setConfirming(false); onApply(rulesDraft(state)); }}>
          Make the whole spaces readable
        </button>
        <button type="button" className="admin-panel__action-btn" onClick={() => setConfirming(false)}>
          Cancel, choose pages
        </button>
      </div>
    </div>
  );
}

type LevelLoad = {
  readJson: ReadJson;
  treeUrl: string;
  setLevels: Dispatch<SetStateAction<Record<string, Level>>>;
  setState: Dispatch<SetStateAction<PickerState | null>>;
};

// Reads one tree level (a page of children from `start`) into the levels and the picker state.
async function loadLevel({ readJson, treeUrl, setLevels, setState }: LevelLoad, space: string, parent: string | null, start: number) {
  const key = levelKey(space, parent);
  setLevels((prev) => ({ ...prev, [key]: { pages: prev[key]?.pages ?? [], nextStart: null, loading: true, error: null } }));
  try {
    const level = await readLevel(readJson, space, parent, start, treeUrl);
    setState((prev) => (prev ? withLevel(prev, space, parent, level.pages) : prev));
    setLevels((prev) => ({
      ...prev,
      [key]: { pages: [...(start ? prev[key]?.pages ?? [] : []), ...level.pages], nextStart: level.nextStart,
        loading: false, error: null },
    }));
  } catch (error) {
    setLevels((prev) => ({ ...prev, [key]: { pages: prev[key]?.pages ?? [], nextStart: null, loading: false,
      error: levelError(error) } }));
  }
}

function PickerUnreadable({ onClose }: { onClose: () => void }) {
  return (
    <div className="page-picker" role="dialog" aria-label="Choose pages">
      <p className="security-field-hint security-field-hint--error" role="alert">
        The stored page list is not a list. Correct it under Advanced first.
      </p>
      <button type="button" className="admin-panel__action-btn" onClick={onClose}>Close</button>
    </div>
  );
}

// "Choose pages" (delivery 5): per allowed space either the whole space or only chosen pages; a lazily
// loaded, read-only page tree where each page is "page and all below", "this page only" or excluded (exclusions
// inside an included branch are allowed). Apply writes confluence_allowed_pages into the draft; Save stores it.
export function ConfluencePagePicker({
  spaces, draftValue, readJson, treeUrl = PAGE_TREE_URL, servedBy = {}, onApply, onClose,
}: Props) {
  const [state, setState] = useState<PickerState | null>(() => pickerState(draftValue, spaces));
  const [levels, setLevels] = useState<Record<string, Level>>({});
  const [open, setOpen] = useState<Record<string, boolean>>({});
  // "Nothing chosen" asks first: whole spaces (no page restriction) or cancel; it is never applied silently.
  const [confirming, setConfirming] = useState(false);

  const load = (space: string, parent: string | null, start = 0) => loadLevel({ readJson, treeUrl, setLevels, setState }, space, parent, start);

  const toggle = (space: string, parent: string | null) => {
    const key = levelKey(space, parent);
    const next = !open[key];
    setOpen((prev) => ({ ...prev, [key]: next }));
    if (next && !levels[key]) void load(space, parent);
  };
  const more = (space: string, parent: string | null) => void load(space, parent, levels[levelKey(space, parent)]?.nextStart ?? 0);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => { if (event.key === "Escape") onClose(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  if (state === null) return <PickerUnreadable onClose={onClose} />;
  const onChoose = (pageId: string, choice: Choice | null) => setState(choose(state, pageId, choice));
  const empty = nothingChosen(state);
  return (
    <div className="page-picker" role="dialog" aria-label="Choose pages" data-testid="confluence-page-picker">
      <div className="page-picker__head">
        <strong>Choose pages</strong>
        <span className="admin-panel__hint">Read-only view of Confluence, with the account that serves each space.</span>
      </div>
      {spaces.length === 0 ? <p className="admin-panel__hint">Add an allowed space first.</p> : null}
      {spaces.map((space) => (
        <PickerSpace key={space} space={space} state={state} levels={levels} open={open} servedBy={servedBy} setState={setState}
          toggle={toggle} more={more} onChoose={onChoose} />
      ))}
      {empty && !confirming ? (
        <p className="security-field-hint security-field-hint--attention" role="status">
          No page is chosen yet.
        </p>
      ) : null}
      {confirming && empty ? <PickerConfirm state={state} setConfirming={setConfirming} onApply={onApply} /> : null}
      <div className="connector-card__actions">
        <button type="button" className="admin-panel__action-btn admin-panel__action-btn--primary"
          disabled={confirming && empty}
          onClick={() => (empty ? setConfirming(true) : onApply(rulesDraft(state)))}>Apply</button>
        <button type="button" className="admin-panel__action-btn" onClick={onClose}>Cancel</button>
      </div>
      <p className="admin-panel__hint">Apply changes the form only; Save stores it.</p>
    </div>
  );
}
