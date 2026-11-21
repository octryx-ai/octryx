import { useState } from "react";
import type { AdminConnector } from "../types/adminPanelTypes.usersProviders";
import type { ConnectorSaveOutcome } from "../hooks/connectorCoreRequests";
import { SECRET_REBIND_REQUIRED } from "./secretRebindModel";
import { blockedReentry, flowAtStep, refusedFlow } from "./secretRebindFlow";
import type { SecretRebindFlow } from "./secretRebindFlow";

type SaveConnector = (
  toolName: string,
  connector: AdminConnector,
  confirmedBody?: Record<string, unknown>,
) => Promise<ConnectorSaveOutcome>;

export type ConnectorRebindFlow = SecretRebindFlow<Record<string, unknown>>;

export function connectorFieldInputId(toolName: string, field: string): string {
  return `connector-field-${toolName}-${field}`;
}

function focusField(toolName: string, field: string | undefined) {
  if (!field) return;
  requestAnimationFrame(() => document.getElementById(connectorFieldInputId(toolName, field))?.focus());
}

// The admin connector card's save with the secret_rebind_required refusal as an explicit state.
export function useConnectorSecretRebind(
  connector: AdminConnector,
  draft: Record<string, string>,
  handleSaveConnector: SaveConnector,
) {
  const toolName = connector.tool_name;
  const [flow, setFlow] = useState<ConnectorRebindFlow | null>(null);

  const apply = (outcome: ConnectorSaveOutcome) => {
    if (outcome.state === SECRET_REBIND_REQUIRED) setFlow(refusedFlow(outcome.refusal, outcome.body));
    else if (outcome.state === "saved") setFlow(null);
  };

  const save = async () => {
    const blocked = blockedReentry(flow, draft);
    if (blocked) {
      setFlow(blocked);
      focusField(toolName, blocked.missing[0]);
      return;
    }
    apply(await handleSaveConnector(toolName, connector));
  };

  // The second, explicit click: the refused body goes out unchanged, plus confirm_secret_rebind=true.
  const confirm = async () => {
    if (flow?.step !== "confirm") return;
    apply(await handleSaveConnector(toolName, connector, flow.body));
  };

  const chooseReenter = () => {
    if (!flow) return;
    setFlow(flowAtStep(flow, "reenter"));
    focusField(toolName, flow.refusal.keptFields[0]);
  };

  // Editing anything but a kept secret changes what was refused, so the refusal and its confirm step no longer apply.
  const fieldEdited = (field: string) => {
    if (!flow) return;
    if (!flow.refusal.keptFields.includes(field)) setFlow(null);
    else if (flow.error) setFlow({ ...flow, error: null, missing: flow.missing.filter((name) => name !== field) });
  };

  return {
    flow,
    save,
    confirm,
    chooseReenter,
    chooseConfirm: () => flow && setFlow(flowAtStep(flow, "confirm")),
    backToChoice: () => flow && setFlow(flowAtStep(flow, "choose")),
    fieldEdited,
  };
}

export type ConnectorSecretRebind = ReturnType<typeof useConnectorSecretRebind>;
