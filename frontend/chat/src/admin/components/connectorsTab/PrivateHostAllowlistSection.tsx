import { useState } from "react";
import { useAdminPrivateHostAllowlist } from "../../hooks/useAdminPrivateHostAllowlist";
import { PrivateHostConnectionCard } from "./PrivateHostConnectionCard";
import "../automation/automationPages.css";
import {
  connectionLabel,
  partitionAllowlistDrafts,
} from "./privateHostAllowlistModel";
import { LoadingState } from "../../../layout/LoadingState";

type PrivateHostAllowlistSectionProps = {
  /** Tool names of configured connectors; their connection types get a form. */
  configuredConnectors: string[];
};

export function PrivateHostAllowlistSection({
  configuredConnectors,
}: PrivateHostAllowlistSectionProps) {
  const state = useAdminPrivateHostAllowlist();
  const [opened, setOpened] = useState<string[]>([]);
  const [choice, setChoice] = useState("");
  const { shown, hidden } = partitionAllowlistDrafts(
    state.drafts,
    configuredConnectors,
    opened,
  );

  return (
    // A collapsed section; no Reload (it silently discarded unsaved entries).
    <details className="automation-details" aria-labelledby="private-host-allowlist-title">
      <summary id="private-host-allowlist-title">
        Private hosts (on-premises systems)
        {state.drafts.some((draft) => draft.saved.length) ? ` · ${state.drafts.reduce((sum, draft) => sum + draft.saved.length, 0)} allowed` : ""}
      </summary>
      {state.loadError ? (
        <div className="admin-panel__error">The allowlist could not be loaded.</div>
      ) : null}
      {state.loading && state.drafts.length === 0 ? (
        <LoadingState label="the allowlist" rows={2} />
      ) : null}
      {!state.loading && shown.length === 0 && !state.loadError ? (
        <div className="admin-panel__empty-state">No on-prem hosts are allowed.</div>
      ) : null}
      {shown.map((draft) => (
        <PrivateHostConnectionCard
          key={draft.connection}
          draft={draft}
          state={state}
        />
      ))}
      {hidden.length > 0 ? (
        <form
          className="admin-panel__toolbar"
          onSubmit={(event) => {
            event.preventDefault();
            if (!choice) return;
            setOpened((current) => [...current, choice]);
            setChoice("");
          }}
        >
          <label htmlFor="private-host-add-type" className="admin-panel__form-label">
            Connection type
          </label>
          <select
            id="private-host-add-type"
            className="admin-panel__input"
            value={choice}
            onChange={(event) => setChoice(event.target.value)}
          >
            <option value="">Select a connection type</option>
            {hidden.map((draft) => (
              <option key={draft.connection} value={draft.connection}>
                {connectionLabel(draft.connection)}
              </option>
            ))}
          </select>
          <button
            type="submit"
            className="admin-panel__action-btn"
            disabled={!choice}
          >
            Add on-prem host
          </button>
        </form>
      ) : null}
    </details>
  );
}
