import { effective } from "./confluencePagePickerModel";
import type { Choice, PageNode, PickerState } from "./confluencePagePickerModel";
import { levelKey } from "./confluencePageTreeApi";
import type { Level } from "./confluencePageTreeApi";

type Props = {
  space: string;
  node: PageNode;
  state: PickerState;
  levels: Record<string, Level>;
  open: Record<string, boolean>;
  onToggle: (space: string, pageId: string) => void;
  onMore: (space: string, parent: string | null) => void;
  onChoose: (pageId: string, choice: Choice | null) => void;
};

const CHOICES: Array<{ value: Choice | ""; label: string }> = [
  { value: "", label: "As above" },
  { value: "subtree", label: "Page and all below" },
  { value: "page", label: "This page only" },
  { value: "excluded", label: "Excluded (with all below)" },
];

// One page of the tree: its choice, whether it is readable (and whether that is inherited), and, when opened, its
// child pages, loaded on demand one level at a time.
export function ConfluencePageTreeNode({ space, node, state, levels, open, onToggle, onMore, onChoose }: Props) {
  const key = levelKey(space, node.id);
  const level = levels[key];
  const isOpen = Boolean(open[key]);
  const result = effective(state, node.id);
  return (
    <li className="page-picker__node" data-page-id={node.id}>
      <div className="page-picker__row">
        <button type="button" className="page-picker__toggle" aria-expanded={isOpen}
          aria-label={`${isOpen ? "Close" : "Open"} ${node.title}`} onClick={() => onToggle(space, node.id)}>
          {isOpen ? "▾" : "▸"}
        </button>
        <span className="page-picker__title">{node.title}</span>
        <span className={`page-picker__state page-picker__state--${result.included ? "in" : "out"}`}
          data-testid={`page-state-${node.id}`}>
          {result.included ? "Readable" : "Not readable"}{result.inherited ? " · inherited" : ""}
        </span>
        <select className="page-picker__choice" aria-label={`Choice for ${node.title}`}
          value={state.choices[node.id] ?? ""}
          onChange={(event) => onChoose(node.id, (event.target.value || null) as Choice | null)}>
          {CHOICES.map((choice) => <option key={choice.value} value={choice.value}>{choice.label}</option>)}
        </select>
      </div>
      {isOpen ? (
        <div className="page-picker__children">
          {level?.error ? <p className="security-field-hint security-field-hint--error" role="alert">{level.error}</p> : null}
          {level?.pages.length ? (
            <ul className="page-picker__list">
              {level.pages.map((child) => (
                <ConfluencePageTreeNode key={child.id} space={space} node={child} state={state} levels={levels}
                  open={open} onToggle={onToggle} onMore={onMore} onChoose={onChoose} />
              ))}
            </ul>
          ) : level && !level.loading && !level.error ? <p className="admin-panel__hint">No child pages.</p> : null}
          {level?.loading ? <p className="admin-panel__hint">Loading…</p> : null}
          {level?.nextStart !== null && level?.nextStart !== undefined && !level.loading ? (
            <button type="button" className="admin-panel__action-btn" onClick={() => onMore(space, node.id)}>
              More pages
            </button>
          ) : null}
        </div>
      ) : null}
    </li>
  );
}
