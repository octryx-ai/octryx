import { useState } from "react";

import { ConfiguredConnectorActions } from "./ConfiguredConnectorActions";
import { ConfiguredConnectorFieldsPanel } from "./ConfiguredConnectorFieldsPanel";
import { ConfiguredConnectorGithubPanel } from "./ConfiguredConnectorGithubPanel";
import { ConfiguredConnectorHeader } from "./ConfiguredConnectorHeader";
import { ConfiguredConnectorHealthTools } from "./ConfiguredConnectorHealthTools";
import { ConfiguredConnectorToolList } from "./ConfiguredConnectorToolList";
import { atlassianAuthView } from "./atlassianAuthView";
import { ConfluenceConnectorSetupFields } from "./ConfluenceConnectorSetupFields";
import { JiraConnectorSetupFields } from "./JiraConnectorSetupFields";
import { ServiceNowConnectorSetupFields } from "./ServiceNowConnectorSetupFields";
import { serviceNowSetupView } from "./serviceNowApiModel";
import { jiraSetupHasErrors, jiraSetupView } from "./jiraConnectorSetupModel";
import { NamedConnections } from "../namedConnections/NamedConnections";
import { namedConnector } from "../namedConnections/namedConnectionsParse";
import { useNamedDescriptors } from "../namedConnections/useNamedDescriptors";
import { SecretRebindPanel } from "../../secretRebind/SecretRebindPanel";
import { useConnectorSecretRebind } from "../../secretRebind/useConnectorSecretRebind";

type ConfiguredConnectorCardProps = {
  connector: any;
  ctx: Record<string, unknown>;
  // Rendered inside the connector drawer (no card header; the grid card opens the drawer).
  inDrawer?: boolean;
};

export function ConfiguredConnectorCard({
  connector,
  ctx,
  inDrawer = false,
}: ConfiguredConnectorCardProps) {
  const {
    CONNECTOR_COLORS,
    expandedConnector,
    getConnectorDraft,
    handleSaveConnector,
    readJson,
  } = ctx as Record<string, any>;

  const isOpen = expandedConnector === connector.tool_name;
  const draft = getConnectorDraft(connector.tool_name);
  const health = connector.health ?? null;
  const iconColor = CONNECTOR_COLORS[connector.tool_name] || "#666";
  const rebind = useConnectorSecretRebind(connector, draft, handleSaveConnector);
  // Every connector type with a server descriptor may hold several global accounts beside this one (the
  // "default"); the registry says which, so this card names no connector type.
  const named = namedConnector(connector.tool_name, useNamedDescriptors(readJson));
  const views = guidedViews(connector, draft);
  const guidedErrors = guidedErrorsFor(views);
  const [saveAttempted, setSaveAttempted] = useState(false);
  const save = () => {
    if (guidedErrors) {
      setSaveAttempted(true);
      return;
    }
    void rebind.save();
  };

  const body = (
    <ConnectorCardBody connector={connector} ctx={ctx} inDrawer={inDrawer} draft={draft} views={views} rebind={rebind}
      saveAttempted={saveAttempted} onSave={save} guidedErrors={guidedErrors} named={named} />
  );
  if (inDrawer) return body;

  return (
    <div
      className={`connector-card ${isOpen ? "connector-card--open" : ""} ${connector.configured ? "connector-card--configured" : ""}`}
    >
      <ConfiguredConnectorHeader
        connector={connector}
        health={health}
        iconColor={iconColor}
        isOpen={isOpen}
        ctx={ctx}
      />
      {isOpen && body}
    </div>
  );
}

type GuidedViews = {
  jiraView: ReturnType<typeof jiraSetupView> | null;
  confluenceView: ReturnType<typeof atlassianAuthView> | null;
  serviceNowView: ReturnType<typeof serviceNowSetupView> | null;
};

function guidedViews(connector: any, draft: any): GuidedViews {
  // Jira has a guided form: a save with draft errors is stopped and every error is shown inline.
  const jiraView =
    connector.tool_name === "jira" ? jiraSetupView(connector, draft) : null;
  // Confluence gets the same guided sign-in (Atlassian Cloud or own instance) and the same stop.
  const confluenceView =
    connector.tool_name === "confluence"
      ? atlassianAuthView("confluence", connector, draft)
      : null;
  // ServiceNow gets an explicit sign-in method and the API section (Table or Scripted REST).
  const serviceNowView =
    connector.tool_name === "servicenow"
      ? serviceNowSetupView(connector, draft)
      : null;
  return { jiraView, confluenceView, serviceNowView };
}

function guidedErrorsFor({ jiraView, confluenceView, serviceNowView }: GuidedViews): boolean {
  return jiraView
    ? jiraSetupHasErrors(jiraView)
    : confluenceView
      ? Object.keys(confluenceView.errors).length > 0
      : serviceNowView
        ? Object.keys(serviceNowView.errors).length > 0
        : false;
}

function testNoteFor({ jiraView, confluenceView, serviceNowView }: GuidedViews): string | undefined {
  return jiraView
    ? "Checks the saved URL and account only, not unsaved changes and not access to the listed projects."
    : confluenceView
      ? "Checks the saved URL and account only, not unsaved changes and not access to the listed spaces."
      : serviceNowView
        ? "Checks the saved URL and sign-in only, not unsaved changes and not access to the allowed tables."
        : undefined;
}

type BodyProps = {
  connector: any;
  ctx: Record<string, unknown>;
  inDrawer: boolean;
  draft: any;
  views: GuidedViews;
  rebind: ReturnType<typeof useConnectorSecretRebind>;
  saveAttempted: boolean;
  onSave: () => void;
  guidedErrors: boolean;
  named: ReturnType<typeof namedConnector>;
};

function ConnectorCardBody({ connector, ctx, inDrawer, draft, views, rebind, saveAttempted, onSave, guidedErrors, named }: BodyProps) {
  const ctxValues = ctx as Record<string, any>;
  const guided = Boolean(views.jiraView || views.confluenceView || views.serviceNowView);
  return (
    <div className="connector-card__body">
      {/* In the side panel the connector's description is not repeated: the Connector settings help has it. */}
      {inDrawer ? null : <p className="connector-card__description">{connector.description}</p>}
      <GuidedOrPlainFields connector={connector} draft={draft} views={views} ctx={ctx} rebind={rebind} showAllErrors={saveAttempted} />
      {rebind.flow ? (
        <SecretRebindPanel
          flow={rebind.flow}
          busy={ctxValues.connectorSaving === connector.tool_name}
          onReenter={rebind.chooseReenter}
          onConfirmStep={() => void rebind.chooseConfirm()}
          onConfirm={() => void rebind.confirm()}
          onBack={() => void rebind.backToChoice()}
        />
      ) : null}
      <ConfiguredConnectorActions
        connector={connector}
        testResult={ctxValues.connectorTestResult[connector.tool_name]}
        ctx={ctx}
        onSave={onSave}
        saveBlockedMessage={
          guided && saveAttempted && guidedErrors
            ? "Not saved: fix the highlighted fields."
            : null
        }
        testLabel={guided ? "Test saved connection" : undefined}
        testNote={testNoteFor(views)}
      />
      {named && ctxValues.readJson ? (
        <NamedConnections
          projectId={null}
          connector={named.connector}
          label={connector.label || connector.tool_name}
          readJson={ctxValues.readJson}
        />
      ) : null}
      {connector.tool_name === "github" ? (
        <ConfiguredConnectorGithubPanel connector={connector} ctx={ctx} />
      ) : null}
      <ConfiguredConnectorHealthTools
        connector={connector}
        healthHistory={ctxValues.connectorHealthHistory[connector.tool_name] || []}
        ctx={ctx}
      />
      <ConfiguredConnectorToolList tools={connector.tools || []} />
    </div>
  );
}

function GuidedOrPlainFields({
  connector,
  draft,
  views,
  ctx,
  rebind,
  showAllErrors,
}: Pick<BodyProps, "connector" | "draft" | "views" | "ctx" | "rebind"> & { showAllErrors: boolean }) {
  return views.jiraView ? (
    <JiraConnectorSetupFields
      connector={connector}
      draft={draft}
      view={views.jiraView}
      ctx={ctx}
      rebind={rebind}
      showAllErrors={showAllErrors}
    />
  ) : views.confluenceView ? (
    <ConfluenceConnectorSetupFields
      connector={connector}
      draft={draft}
      view={views.confluenceView}
      ctx={ctx}
      rebind={rebind}
      showAllErrors={showAllErrors}
    />
  ) : views.serviceNowView ? (
    <ServiceNowConnectorSetupFields
      connector={connector}
      draft={draft}
      view={views.serviceNowView}
      ctx={ctx}
      rebind={rebind}
      showAllErrors={showAllErrors}
    />
  ) : (
    <ConfiguredConnectorFieldsPanel
      connector={connector}
      draft={draft}
      ctx={ctx}
      rebind={rebind}
    />
  );
}
