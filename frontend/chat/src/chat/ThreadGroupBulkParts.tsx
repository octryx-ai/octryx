import type { ThreadSummary } from "../chatThreadTypes";
import type { GroupCheckState } from "./threadSelection";
import { ThreadCheckboxBox } from "./threadSidebarIcons";

export type ThreadGroupBanner =
  | { kind: "offer"; shown: number; total: number; label: string }
  | { kind: "scope"; selected: number; total: number; notLoaded: number; label: string };

/** Bulk-mode wiring of one group; absent outside bulk mode. */
export type ThreadGroupBulk = {
  checkState: GroupCheckState;
  isSelected: (threadId: string) => boolean;
  onToggleRow: (thread: ThreadSummary, shift: boolean) => void;
  onGroupCheck: () => void;
  banner: ThreadGroupBanner | null;
  onSelectScope: () => void;
  onClearScope: () => void;
};

export function GroupCheckbox({
  state,
  label,
  onChange,
}: {
  state: GroupCheckState;
  label: string;
  onChange: () => void;
}) {
  return (
    <label className="thread-card__checkbox thread-group__check" title={label}>
      <input
        type="checkbox"
        checked={state === "visible" || state === "scope"}
        ref={(input) => {
          if (input) {
            input.indeterminate = state === "some";
          }
        }}
        aria-label={label}
        onChange={onChange}
      />
      <ThreadCheckboxBox />
    </label>
  );
}

export function GroupBanner({
  banner,
  onSelectScope,
  onClearScope,
}: {
  banner: ThreadGroupBanner;
  onSelectScope: () => void;
  onClearScope: () => void;
}) {
  if (banner.kind === "offer") {
    return (
      <div className="thread-group__banner" role="status">
        <span>
          The <strong>{banner.shown}</strong> shown are selected.
        </span>
        <button type="button" className="thread-group__banner-link" onClick={onSelectScope}>
          Select all {banner.total} {banner.label}
        </button>
      </div>
    );
  }
  return (
    <div className="thread-group__banner" role="status">
      <span>
        {banner.selected === banner.total ? (
          <>
            All <strong>{banner.selected}</strong>
          </>
        ) : (
          <>
            <strong>{banner.selected}</strong> of {banner.total}
          </>
        )}{" "}
        chats {banner.label} are selected
        {banner.notLoaded ? ` — ${banner.notLoaded} of them not loaded yet` : ""}.
      </span>
      <button type="button" className="thread-group__banner-link" onClick={onClearScope}>
        Clear
      </button>
    </div>
  );
}
