// Workspace › Data › Connectors: the parts of a connector's access panel (limits and own connections).
import { FormSection } from "../../../layout/FormSection";
import { NamedConnections } from "../namedConnections/NamedConnections";
import { WorkspaceConfluencePages } from "./WorkspaceConfluencePages";
import { WorkspaceConnectorConnection } from "./WorkspaceConnectorConnection";
import type { connectionProduct } from "./workspaceConnectionModel";
import { KNOWN_LIMIT_FIELDS, labelForLimitField } from "./ProjectConnectorSettingsHelpers";
import type { ConnectorDraft, ProjectConnectorAccess } from "./ProjectConnectorSettingsHelpers";
import { KeyTagInput } from "../keyTags/KeyTagInput";
import { splitKeys } from "../keyTags/keyTagsModel";
import { SPACE_RULE } from "../connectorsTab/confluenceScopeModel";

type ReadJson = <T = unknown>(url: string, init?: RequestInit) => Promise<T>;

// Limits without their own input: one text area each, labelled from the field name.
function GenericLimitFields({ fields, draft, update }: { fields: string[]; draft: ConnectorDraft; update: (patch: Partial<ConnectorDraft>) => void }) {
  return (
    <>
      {fields.map((fieldName) => (
        <label className="admin-form-field" key={fieldName}>
          <span className="admin-form-field__label">{labelForLimitField(fieldName)}</span>
          <textarea
            className="admin-panel__input"
            rows={3}
            value={draft.genericLimits[fieldName] || ""}
            onChange={(event) => update({ genericLimits: { ...draft.genericLimits, [fieldName]: event.target.value } })}
            placeholder="Empty: the platform's values apply"
          />
        </label>
      ))}
    </>
  );
}

// "Workspace limits": the known limit fields with their own inputs, any other limit as plain text.
export function ConnectorAccessLimits({ connector, projectId, readJson, draft, update }: {
  connector: ProjectConnectorAccess;
  projectId: string;
  readJson: ReadJson;
  draft: ConnectorDraft;
  update: (patch: Partial<ConnectorDraft>) => void;
}) {
  const name = connector.connector_name;
  const limitFields = connector.limit_fields || [];
  const genericFields = limitFields.filter((fieldName) => !KNOWN_LIMIT_FIELDS.has(fieldName));
  if (!limitFields.length) return null;
  return (
    <FormSection title="Workspace limits">
      {limitFields.includes("jira_allowed_projects") ? (
        <label className="admin-form-field">
          <span className="admin-form-field__label">Allowed Jira project keys</span>
          <textarea
            className="admin-panel__input"
            rows={3}
            value={draft.jiraProjects}
            onChange={(event) => update({ jiraProjects: event.target.value })}
            placeholder="Empty: the platform's projects apply"
          />
        </label>
      ) : null}
      {limitFields.includes("confluence_allowed_spaces") ? (
        <div className="admin-form-field">
          <label htmlFor={`project-${name}-spaces`}>Allowed Confluence spaces</label>
          <KeyTagInput
            id={`project-${name}-spaces`}
            noun="space"
            keys={splitKeys(draft.confluenceSpaces)}
            rule={SPACE_RULE}
            onChange={(keys) => update({ confluenceSpaces: keys.join("\n") })}
            placeholder="No space: the global spaces apply"
          />
        </div>
      ) : null}
      {limitFields.includes("confluence_allowed_pages") ? (
        <WorkspaceConfluencePages projectId={projectId} access={connector} draft={draft} readJson={readJson} update={update} />
      ) : null}
      {limitFields.includes("bitbucket_allowed_repos") ? (
        <label className="admin-form-field">
          <span className="admin-form-field__label">Allowed Bitbucket repositories</span>
          <textarea
            className="admin-panel__input"
            rows={4}
            value={draft.bitbucketRepos}
            onChange={(event) => update({ bitbucketRepos: event.target.value })}
            placeholder="PROJECT/repository, one per line"
          />
        </label>
      ) : null}
      <GenericLimitFields fields={genericFields} draft={draft} update={update} />
    </FormSection>
  );
}

// This Workspace's own connection (products with one) and its named connections.
export function ConnectorOwnConnections({ connector, projectId, readJson, product, named, markOwnReady }: {
  connector: ProjectConnectorAccess;
  projectId: string;
  readJson: ReadJson;
  product: ReturnType<typeof connectionProduct>;
  named: boolean;
  markOwnReady: (connectorName: string, ready: boolean) => void;
}) {
  const name = connector.connector_name;
  return (
    <>
      {product ? (
        <WorkspaceConnectorConnection
          projectId={projectId}
          connectorName={name}
          product={product}
          label={connector.label}
          readJson={readJson}
          onReadyChange={(ready) => markOwnReady(name, ready)}
        />
      ) : null}

      {named ? (
        <NamedConnections
          projectId={projectId}
          connector={name}
          label={connector.label}
          readJson={readJson}
          onReadyChange={(ready) => markOwnReady(name, ready)}
        />
      ) : null}
    </>
  );
}
