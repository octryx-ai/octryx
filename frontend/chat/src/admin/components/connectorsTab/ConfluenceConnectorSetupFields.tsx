import type { ConnectorSecretRebind } from "../../secretRebind/useConnectorSecretRebind";
import { AtlassianAuthFields } from "./AtlassianAuthFields";
import type { AtlassianAuthView } from "./atlassianAuthView";
import { authOwnedFields } from "./atlassianAuthModes";
import { ConfiguredConnectorFieldsPanel } from "./ConfiguredConnectorFieldsPanel";
import { ConfluenceScopeFields } from "./ConfluenceScopeFields";
import { ConnectorFieldGroup } from "./ConnectorFieldGroup";
import { GROUP_TITLES } from "./connectorFieldGroupsModel";
import { missingFlags, scopeCheckOf } from "../connectorTest/scopeCheckModel";
import { CONFLUENCE_SCOPE_FIELDS, connectionTested } from "./confluenceScopeModel";

type ConfluenceConnectorSetupFieldsProps = {
  connector: any;
  draft: Record<string, string>;
  view: AtlassianAuthView;
  ctx: Record<string, unknown>;
  rebind: ConnectorSecretRebind;
  showAllErrors: boolean;
};

// Confluence: the shared Atlassian URL and sign-in, then the scope (delivery 5: spaces as tags, pages,
// JSON under Advanced); any other preset field stays in the generic panel, which shows no sign-in or scope field.
export function ConfluenceConnectorSetupFields({
  connector,
  draft,
  view,
  ctx,
  rebind,
  showAllErrors,
}: ConfluenceConnectorSetupFieldsProps) {
  const { setConnectorField, readJson, connectorTestResult } = ctx as Record<string, any>;
  const set = (field: string, value: string) => {
    setConnectorField(connector.tool_name, field, value);
    rebind.fieldEdited(field);
  };
  const owned = new Set([...authOwnedFields("confluence"), ...CONFLUENCE_SCOPE_FIELDS]);
  const rest = {
    ...connector,
    fields: (connector.fields || []).filter(
      (field: string) => !owned.has(field),
    ),
  };
  return (
    <>
      {(["connection", "authentication"] as const).map((part) => (
        <ConnectorFieldGroup key={part} group={part} title={GROUP_TITLES[part]}>
          <div className="connector-card__fields">
            <AtlassianAuthFields product="confluence" connector={connector} draft={draft} view={view} set={set}
              rebind={rebind} showAllErrors={showAllErrors} part={part} />
          </div>
        </ConnectorFieldGroup>
      ))}
      <ConfluenceScopeFields toolName={connector.tool_name} draft={draft} set={set}
        browse={readJson ? { readJson, ready: connectionTested(connector, connectorTestResult) } : null}
        flagged={missingFlags(scopeCheckOf(connectorTestResult?.[connector.tool_name]))} />
      {rest.fields.length ? (
        <ConfiguredConnectorFieldsPanel
          connector={rest}
          draft={draft}
          ctx={ctx}
          rebind={rebind}
        />
      ) : null}
    </>
  );
}
