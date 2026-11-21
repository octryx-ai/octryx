import { PanelFooterActions } from "../../../layout/PanelFooterSlot";
import { testResultHint } from "./oidcClientCredentialsModel";
import { endpointResults } from "./serviceNowApiModel";
import { ConnectorScopeCheck } from "../connectorTest/ConnectorScopeCheck";
import { scopeCheckOf } from "../connectorTest/scopeCheckModel";

type ConfiguredConnectorActionsProps = {
  connector: any;
  testResult: any;
  ctx: Record<string, unknown>;
  onSave: () => void;
  // Optional, per connector (Jira): why a save was stopped, and a precise test label and scope note.
  saveBlockedMessage?: string | null;
  testLabel?: string;
  testNote?: string;
};

export function ConfiguredConnectorActions({
  connector,
  testResult,
  ctx,
  onSave,
  saveBlockedMessage = null,
  testLabel = "Test connection",
  testNote,
}: ConfiguredConnectorActionsProps) {
  const { connectorSaving, connectorTesting, handleTestConnector } =
    ctx as Record<string, any>;
  const scopeCheck = scopeCheckOf(testResult);
  const tone = !testResult ? "" : !testResult.ok ? "fail" : testResult.scope_warning ? "warn" : "ok";

  return (
    <>
      {testResult ? (
        <div
          className={`connector-card__test-result connector-card__test-result--${tone}`}
          data-testid="connector-test-result" role="status"
        >
          <strong>{tone === "ok" ? "✓" : tone === "warn" ? "⚠" : "✗"}</strong> {testResult.summary}
          {testResult.details ? (
            <div className="connector-card__test-details">
              {testResult.details}
            </div>
          ) : null}
          {/* A coded failure (token endpoint, client, target system) in plain words. */}
          {/* A Scripted REST test reports each endpoint on its own line. */}
          {endpointResults(testResult).length ? (
            <ul className="connector-card__test-details" data-testid="connector-test-endpoints">
              {endpointResults(testResult).map((line) => (
                <li key={line.endpoint} data-ok={line.ok ? "yes" : "no"}>
                  <strong>{line.ok ? "✓" : "✗"} {line.label}</strong>: {line.text}
                </li>
              ))}
            </ul>
          ) : null}
          {/* Delivery 5: configured versus visible spaces/projects/tables of the tested account. */}
          {scopeCheck ? <ConnectorScopeCheck check={scopeCheck} /> : null}
          {testResultHint(testResult) ? (
            <div className="connector-card__test-details" data-testid="connector-test-hint">
              {testResultHint(testResult)}
            </div>
          ) : null}
        </div>
      ) : null}

      {/* In the connector's side panel Save and the test sit in the panel footer, bottom right
          (primary last); without a panel they stay in place. What the test checks is in the Connector settings help. */}
      <PanelFooterActions>
      <div className="connector-card__actions">
        {connector.supports_test ? (
          <button
            type="button"
            className="admin-panel__action-btn"
            disabled={
              !connector.configured || connectorTesting === connector.tool_name
            }
            onClick={() => void handleTestConnector(connector.tool_name)}
            title={
              connector.configured
                ? testNote ?? "Test connection"
                : "Save configuration first"
            }
            data-testid="connector-test"
          >
            {connectorTesting === connector.tool_name
              ? "Testing…"
              : testLabel}
          </button>
        ) : null}
        <button
          type="button"
          className="admin-panel__action-btn admin-panel__action-btn--primary"
          disabled={connectorSaving === connector.tool_name}
          onClick={onSave}
        >
          {connectorSaving === connector.tool_name ? "Saving…" : "Save"}
        </button>
      </div>
      </PanelFooterActions>
      {saveBlockedMessage ? (
        <div className="jira-setup__notes">
          <p className="security-field-hint security-field-hint--error" role="alert">{saveBlockedMessage}</p>
        </div>
      ) : null}
    </>
  );
}
