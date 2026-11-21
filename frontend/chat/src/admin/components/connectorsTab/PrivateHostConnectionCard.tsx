import type { PrivateHostAllowlistState } from "../../hooks/useAdminPrivateHostAllowlist";
import {
  connectionLabel,
  refusalSentence,
  type PrivateHostDraft,
} from "./privateHostAllowlistModel";

const SMALL_BUTTON = { fontSize: "var(--ds-text-2xs)", padding: "0.18rem 0.45rem" };

type ConnectionCardProps = {
  draft: PrivateHostDraft;
  state: PrivateHostAllowlistState;
};

type PartProps = { state: PrivateHostAllowlistState; busy: boolean };

function PrivateHostRowsTable({ draft, state, busy }: PartProps & { draft: PrivateHostDraft }) {
  const { connection } = draft;
  return (
  <div className="admin-panel__table-wrap">
    <table className="admin-panel__table">
      <thead>
        <tr>
          <th>Host:port</th>
          <th>Status</th>
          <th>Actions</th>
        </tr>
      </thead>
      <tbody>
        {draft.rows.map((row) => (
          <tr key={row.key}>
            <td>
              <code>{row.value}</code>
            </td>
            <td>
              {row.refusal ? (
                <span className="admin-panel__error">
                  Refused: {refusalSentence(row.refusal)}
                </span>
              ) : (
                <span className="admin-panel__cell--muted">
                  {draft.saved.includes(row.value) ? "Saved" : "New"}
                </span>
              )}
            </td>
            <td>
              <button
                type="button"
                className="admin-panel__danger-btn"
                style={SMALL_BUTTON}
                disabled={busy}
                onClick={() => state.remove(connection, row.key)}
              >
                Remove
              </button>
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  </div>
  );
}

function PrivateHostAddForm({ connection, state, busy, saving, dirty }: PartProps & { connection: string; saving: boolean; dirty: boolean }) {
  const inputId = `private-host-entry-${connection}`;
  return (
    <form
      className="admin-panel__toolbar"
      onSubmit={(event) => {
        event.preventDefault();
        state.add(connection);
      }}
    >
      <label htmlFor={inputId} className="admin-panel__form-label">
        Add host:port
      </label>
      <input
        id={inputId}
        className="admin-panel__form-input"
        value={state.inputs[connection] ?? ""}
        disabled={busy}
        onChange={(event) => state.setInput(connection, event.target.value)}
      />
      <button
        type="submit"
        className="admin-panel__action-btn"
        disabled={busy}
      >
        Add
      </button>
      <button
        type="button"
        className="admin-panel__action-btn"
        disabled={busy || !dirty}
        onClick={() => void state.save(connection)}
      >
        {saving ? "Saving..." : "Save"}
      </button>
      <button
        type="button"
        className="admin-panel__action-btn"
        disabled={busy || !dirty}
        onClick={() => state.discard(connection)}
      >
        Discard changes
      </button>
    </form>
  );
}

export function PrivateHostConnectionCard({ draft, state }: ConnectionCardProps) {
  const { connection } = draft;
  const saving = state.savingConnection === connection;
  const busy = state.savingConnection !== null;
  const inputRefusal = state.inputRefusals[connection] ?? null;

  return (
    <div className="admin-panel__card" data-connection={connection}>
      <div className="admin-panel__section-header">
        <span>
          {connectionLabel(connection)} ({draft.rows.length})
        </span>
        {draft.dirty ? (
          <span className="admin-panel__badge admin-panel__badge--warning">
            Unsaved
          </span>
        ) : null}
      </div>
      {draft.rows.length === 0 ? (
        <div className="admin-panel__empty-state">
          No private hosts allowed. On-prem targets on private addresses are
          refused.
        </div>
      ) : (
        <PrivateHostRowsTable draft={draft} state={state} busy={busy} />
      )}
      {draft.listRefusal ? (
        <div className="admin-panel__error">
          Save refused: <code>{draft.listRefusal}</code>
        </div>
      ) : null}
      <PrivateHostAddForm connection={connection} state={state} busy={busy} saving={saving} dirty={draft.dirty} />
      {inputRefusal ? (
        <div className="admin-panel__error">
          Not added: <code>{inputRefusal}</code>
        </div>
      ) : null}
    </div>
  );
}
