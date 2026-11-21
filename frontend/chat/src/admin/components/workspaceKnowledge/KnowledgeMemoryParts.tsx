// The parts of a Workspace's memory page: the capture and lesson switches, and one row per memory with its actions.
import { CONFIRM_ROLE_CHOICES, memoryApi } from "./memoryApi";
import type { MemoryItem, MemoryOverview } from "./memoryApi";

const STATE_BADGE: Record<MemoryItem["state"], string> = {
  confirmed: "admin-panel__badge--active",
  observed: "admin-panel__badge--warning",
  contradicted: "admin-panel__badge--danger",
  superseded: "admin-panel__badge--inactive",
  expired: "admin-panel__badge--inactive",
  forgotten: "admin-panel__badge--inactive",
  promoted: "admin-panel__badge--secondary",
  proposed: "admin-panel__badge--warning",
};
const ROLE_LABEL: Record<string, string> = { viewer: "Viewer", member: "Member", owner: "Owner", admin: "Platform admin" };
const AUTHOR_TEXT: Record<MemoryItem["author_class"], string> = {
  human_stated: "stated by a person",
  model_inferred: "inferred by the agent",
  verified: "verified against evidence",
};

function MemoryText({ item }: { item: MemoryItem }) {
  if (item.text === null) return <span className="admin-panel__muted">Forgotten: the text was erased.</span>;
  return (
    <>
      <div style={{ whiteSpace: "pre-wrap" }}>{item.text}</div>
      <div className="admin-panel__muted">
        {item.session_link ? <a href={item.session_link}>{item.present_as}</a> : item.present_as}
        {item.recorded_by ? ` · ${item.recorded_by}` : ""}
        {item.product ? ` · ${item.product}` : ""}
      </div>
    </>
  );
}

type Run = (action: () => Promise<unknown>, note?: string) => Promise<void>;
type Editing = { id: string; text: string } | null;

// Automatic capture at turn end, and lessons learned from coding sessions with who may confirm them.
export function MemorySwitches({ overview, workspaceId, busy, run }: {
  overview: MemoryOverview;
  workspaceId: string;
  busy: boolean;
  run: Run;
}) {
  return (
    <>
      <label className="admin-panel__checkbox"
        title={overview.may_author ? undefined : "Needs the Workspace admin or owner role."}>
        <input type="checkbox" checked={overview.automatic_capture} disabled={busy || !overview.may_author}
          onChange={(event) => {
            const enabled = event.target.checked;
            void run(() => memoryApi.setAutomaticCapture(workspaceId, enabled),
              enabled ? "Automatic capture is on." : "Automatic capture is off.");
          }} />
        Capture memories automatically at the end of each turn (inferred by the agent, shown as unconfirmed)
      </label>

      <div className="admin-panel__stack" style={{ gap: "0.4rem" }} data-testid="memory-session-lessons">
        <label className="admin-panel__checkbox"
          title={overview.may_author ? undefined : "Needs the Workspace admin or owner role."}>
          <input type="checkbox" checked={overview.session_lessons ?? false} disabled={busy || !overview.may_author}
            onChange={(event) => {
              const enabled = event.target.checked;
              void run(() => memoryApi.setLessons(workspaceId, { session_lessons: enabled }),
                enabled ? "Lessons learned from coding sessions are on." : "Lessons learned are off.");
            }} />
          Propose lessons learned from coding sessions (octryx) for the team; each one waits here until confirmed
        </label>
        <div className="admin-panel__muted" style={{ display: "flex", alignItems: "center", gap: "0.8rem", flexWrap: "wrap" }}>
          <span>Who may confirm or reject a proposed lesson:</span>
          {CONFIRM_ROLE_CHOICES.map((role) => {
            const roles = overview.confirm_roles ?? ["owner", "admin"];
            return (
              <label key={role} className="admin-panel__checkbox">
                <input type="checkbox" checked={roles.includes(role)} disabled={busy || !overview.may_author}
                  aria-label={`${ROLE_LABEL[role]} may confirm lessons`}
                  onChange={(event) => {
                    const next = event.target.checked ? [...roles, role] : roles.filter((item) => item !== role);
                    void run(() => memoryApi.setLessons(workspaceId, { confirm_roles: next }), "Saved who may confirm.");
                  }} />
                {ROLE_LABEL[role]}
              </label>
            );
          })}
        </div>
      </div>
    </>
  );
}

type RowProps = {
  item: MemoryItem;
  workspaceId: string;
  editing: Editing;
  setEditing: (editing: Editing) => void;
  busy: boolean;
  run: Run;
  saveCorrection: () => void;
  forget: (item: MemoryItem) => void;
};

// Save or cancel a correction, else confirm, reject, correct and forget as the memory's state allows.
function MemoryRowActions({ item, workspaceId, editing, setEditing, busy, run, saveCorrection, forget }: RowProps) {
  return (
    <div className="admin-users__row-actions" style={{ justifyContent: "flex-end" }}>
      {editing?.id === item.id ? (
        <>
          <button type="button" className="admin-panel__action-btn admin-panel__action-btn--primary"
            disabled={busy || !editing.text.trim()} onClick={saveCorrection}>Save</button>
          <button type="button" className="admin-panel__action-btn" disabled={busy}
            onClick={() => setEditing(null)}>Cancel</button>
        </>
      ) : (
        <>
          {item.state === "observed" || item.state === "proposed" ? (
            <button type="button" className="admin-panel__action-btn" disabled={busy}
              onClick={() => void run(() => memoryApi.confirm(workspaceId, item.id), "Confirmed.")}>
              Confirm
            </button>
          ) : null}
          {item.state === "proposed" ? (
            <button type="button" className="admin-panel__action-btn admin-panel__action-btn--danger"
              disabled={busy}
              onClick={() => void run(() => memoryApi.reject(workspaceId, item.id), "Rejected and deleted.")}>
              Reject
            </button>
          ) : null}
          {["observed", "confirmed", "contradicted"].includes(item.state) ? (
            <button type="button" className="admin-panel__action-btn" disabled={busy}
              onClick={() => setEditing({ id: item.id, text: item.text ?? "" })}>Correct</button>
          ) : null}
          <button type="button" className="admin-panel__action-btn admin-panel__action-btn--danger"
            disabled={busy} onClick={() => forget(item)}>Forget</button>
        </>
      )}
    </div>
  );
}

function MemoryRow(props: RowProps) {
  const { item, editing, setEditing } = props;
  return (
    <tr>
      <td style={{ minWidth: "18rem" }}>
        {editing?.id === item.id ? (
          <textarea className="admin-panel__textarea" rows={3} value={editing.text} aria-label="Corrected memory"
            onChange={(event) => setEditing({ id: item.id, text: event.target.value })} />
        ) : (
          <MemoryText item={item} />
        )}
      </td>
      <td>{item.scope}</td>
      <td>{item.class.replace("_", " ")}</td>
      <td className="admin-panel__muted">{AUTHOR_TEXT[item.author_class] ?? item.author_class}</td>
      <td><span className={`admin-panel__badge ${STATE_BADGE[item.state] ?? ""}`}>
        {item.state === "proposed" ? "proposed lesson" : item.state}
      </span></td>
      <td>
        {item.may_change ? <MemoryRowActions {...props} /> : null}
      </td>
    </tr>
  );
}

export function MemoryTable({ items, ...rowProps }: Omit<RowProps, "item"> & { items: MemoryItem[] }) {
  return (
    <div className="admin-panel__table-wrap">
      <table className="admin-panel__table" style={{ border: "none", borderRadius: 0 }}>
        <thead><tr><th>Memory</th><th>Scope</th><th>Class</th><th>Author</th><th>State</th><th /></tr></thead>
        <tbody>
          {items.map((item) => <MemoryRow key={item.id} {...rowProps} item={item} />)}
        </tbody>
      </table>
    </div>
  );
}
