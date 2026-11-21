import { useState } from "react";
import { KeyTagInput } from "../keyTags/KeyTagInput";
import { spacesDraft, spaceTags } from "../keyTags/keyTagsModel";
import { connectorFieldInputId } from "../../secretRebind/useConnectorSecretRebind";
import { PAGES_FIELD, SPACE_RULE, SPACES_FIELD } from "./confluenceScopeModel";
import { ConfluencePagePicker } from "./ConfluencePagePicker";
import { pagesSummary } from "./confluencePagePickerModel";
import type { ReadJson } from "./confluencePageTreeApi";
import { useConfluencePickerSpaces } from "./useConfluencePickerSpaces";
import "./connectorCardGroups.css";

type Props = {
  toolName: string;
  draft: Record<string, string>;
  set: (field: string, value: string) => void;
  // The page picker reads the saved connections; it opens after a successful test of the default or a named one.
  browse?: { readJson: ReadJson; ready: boolean } | null;
  // Spaces the last connection test found configured but not visible to the account (key → reason).
  flagged?: Record<string, string>;
};

// The Confluence scope (delivery 5): allowed spaces as tags (stored as [{space_key, enabled}]), the page
// allowlist in words, and both stored values as JSON under "Advanced" for what the main view cannot express. The
// page list narrows every connection, so the picker also shows the spaces of the named connections.
export function ConfluenceScopeFields({ toolName, draft, set, browse = null, flagged = {} }: Props) {
  const spaces = spaceTags(draft[SPACES_FIELD]);
  const [picking, setPicking] = useState(false);
  const picker = useConfluencePickerSpaces(browse?.readJson ?? null, null, spaces.keys);
  const ready = Boolean(browse?.ready || picker.namedTested);
  const id = (field: string) => connectorFieldInputId(toolName, field);
  return (
    <fieldset className="ds-form-section connector-card__group" data-group="scope" data-testid="confluence-scope">
      <legend className="ds-form-section__title">Scope</legend>
      <div className="connector-field">
        <label className="connector-field__label" htmlFor={id(SPACES_FIELD)}>Allowed spaces</label>
        {spaces.unreadable ? (
          <span className="security-field-hint security-field-hint--error" role="alert">
            The stored value is not a list of spaces. Correct it under Advanced.
          </span>
        ) : (
          <KeyTagInput id={id(SPACES_FIELD)} noun="space" keys={spaces.keys} rule={SPACE_RULE}
            placeholder="SPACE1, SPACE2" flagged={flagged} describedBy={`${id(SPACES_FIELD)}-hint`}
            onChange={(keys) => set(SPACES_FIELD, spacesDraft(draft[SPACES_FIELD], keys))} />
        )}
        <span className="admin-panel__hint" id={`${id(SPACES_FIELD)}-hint`}>
          One space key per tag. Agents and Source Sync read only these spaces; no space means none.
          {spaces.disabled.length ? ` Stored as disabled (not readable): ${spaces.disabled.join(", ")}.` : ""}
        </span>
      </div>
      <div className="connector-field">
        <span className="connector-field__label">Allowed pages</span>
        <span className="admin-panel__hint" data-testid="confluence-pages-summary">{pagesSummary(draft[PAGES_FIELD])}</span>
        {browse ? (
          <div className="connector-card__actions">
            <button type="button" className="admin-panel__action-btn" disabled={!ready || picking}
              onClick={() => void picker.reload().then(() => setPicking(true))}>Choose pages</button>
            {!ready ? <span className="admin-panel__hint">Test the saved connection first.</span> : null}
          </div>
        ) : null}
        {browse && picking ? (
          <ConfluencePagePicker spaces={picker.spaces} servedBy={picker.servedBy} draftValue={draft[PAGES_FIELD]}
            readJson={browse.readJson}
            onClose={() => setPicking(false)}
            onApply={(value) => { set(PAGES_FIELD, value); setPicking(false); }} />
        ) : null}
      </div>
      <details className="connector-card__advanced">
        <summary>Advanced: stored values as JSON</summary>
        <div className="connector-field">
          <label className="connector-field__label" htmlFor={id(`${SPACES_FIELD}-json`)}>Allowed spaces (JSON)</label>
          <textarea id={id(`${SPACES_FIELD}-json`)} className="connector-field__input connector-field__input--textarea"
            value={draft[SPACES_FIELD] ?? ""} rows={4} spellCheck={false}
            onChange={(event) => set(SPACES_FIELD, event.target.value)} />
        </div>
        <div className="connector-field">
          <label className="connector-field__label" htmlFor={id(`${PAGES_FIELD}-json`)}>Allowed pages (JSON)</label>
          <textarea id={id(`${PAGES_FIELD}-json`)} className="connector-field__input connector-field__input--textarea"
            value={draft[PAGES_FIELD] ?? ""} rows={6} spellCheck={false}
            onChange={(event) => set(PAGES_FIELD, event.target.value)} />
        </div>
      </details>
    </fieldset>
  );
}
