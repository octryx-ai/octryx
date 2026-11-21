import { useState } from "react";
import { ConfluencePagePicker } from "../connectorsTab/ConfluencePagePicker";
import { pageTreeUrl } from "../connectorsTab/confluencePageTreeApi";
import type { ReadJson } from "../connectorsTab/confluencePageTreeApi";
import { useConfluencePickerSpaces } from "../connectorsTab/useConfluencePickerSpaces";
import { draftPageEntries, pageEntriesPatch, workspaceAllowedSpaces } from "./ProjectConnectorSettingsHelpers";
import type { ConnectorDraft, ProjectConnectorAccess } from "./ProjectConnectorSettingsHelpers";

type Props = {
  projectId: string;
  access: ProjectConnectorAccess;
  draft: ConnectorDraft;
  readJson: ReadJson;
  update: (patch: Partial<ConnectorDraft>) => void;
};

// A Workspace's Confluence page limit: the one-line-per-page text, and "Choose pages" with the page tree of
// every space this Workspace reads (its allowed spaces and those of its own and the inherited named connections),
// each space read with the connection that serves it here (not only the first connection).
export function WorkspaceConfluencePages({ projectId, access, draft, readJson, update }: Props) {
  const [picking, setPicking] = useState(false);
  const picker = useConfluencePickerSpaces(readJson, projectId, workspaceAllowedSpaces(draft, access));
  return (
    <div className="admin-form-field">
      <label htmlFor={`project-${access.connector_name}-pages`}>Allowed Confluence pages</label>
      <textarea
        id={`project-${access.connector_name}-pages`}
        className="admin-panel__form-input connector-field__input--textarea"
        rows={3}
        value={draft.confluencePages}
        onChange={(event) => update({ confluencePages: event.target.value })}
        placeholder="pageId | optional title | optional space"
      />
      <div className="connector-card__actions">
        <button type="button" className="admin-panel__action-btn" disabled={picking}
          onClick={() => void picker.reload().then(() => setPicking(true))}>Choose pages</button>
      </div>
      {picking ? (
        <ConfluencePagePicker spaces={picker.spaces} servedBy={picker.servedBy} treeUrl={pageTreeUrl(projectId)}
          draftValue={JSON.stringify(draftPageEntries(draft))} readJson={readJson}
          onClose={() => setPicking(false)}
          onApply={(value) => { update(pageEntriesPatch(JSON.parse(value))); setPicking(false); }} />
      ) : null}
    </div>
  );
}
