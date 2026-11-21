// Draft editing of a connector: its field values and its tool policy (instructions, extra and disabled tools).
import type { ConnectorPolicyDraft, UseAdminConnectorManagementArgs } from "./useAdminConnectorManagement.types";

type ConnectorDraftDeps = Pick<
  UseAdminConnectorManagementArgs,
  "connectorDraft" | "setConnectorDraft" | "connectorPolicyDraft" | "setConnectorPolicyDraft"
>;

export function connectorDraftActions({
  connectorDraft,
  setConnectorDraft,
  connectorPolicyDraft,
  setConnectorPolicyDraft,
}: ConnectorDraftDeps) {
  const getConnectorDraft = (toolName: string) =>
    connectorDraft[toolName] || {};

  const getConnectorPolicyDraft = (toolName: string): ConnectorPolicyDraft =>
    connectorPolicyDraft[toolName] || {
      tool_instructions: "",
      extra_tools: [],
      disabled_tools: [],
    };

  const setConnectorField = (
    toolName: string,
    field: string,
    value: string,
  ) => {
    setConnectorDraft((prev) => ({
      ...prev,
      [toolName]: { ...(prev[toolName] || {}), [field]: value },
    }));
  };

  const setConnectorPolicyField = (
    toolName: string,
    field: "tool_instructions" | "extra_tools" | "disabled_tools",
    value: string | string[],
  ) => {
    setConnectorPolicyDraft((prev) => ({
      ...prev,
      [toolName]: {
        ...getConnectorPolicyDraft(toolName),
        [field]: value,
      },
    }));
  };

  const addConnectorExtraTool = (toolName: string, extraToolName: string) => {
    const draft = getConnectorPolicyDraft(toolName);
    if (draft.extra_tools.includes(extraToolName)) return;
    setConnectorPolicyField(toolName, "extra_tools", [
      ...draft.extra_tools,
      extraToolName,
    ]);
  };

  const removeConnectorExtraTool = (
    toolName: string,
    extraToolName: string,
  ) => {
    const draft = getConnectorPolicyDraft(toolName);
    setConnectorPolicyField(
      toolName,
      "extra_tools",
      draft.extra_tools.filter((name) => name !== extraToolName),
    );
  };

  const toggleConnectorDisabledTool = (
    toolName: string,
    disabledToolName: string,
  ) => {
    const draft = getConnectorPolicyDraft(toolName);
    if (draft.disabled_tools.includes(disabledToolName)) {
      setConnectorPolicyField(
        toolName,
        "disabled_tools",
        draft.disabled_tools.filter((name) => name !== disabledToolName),
      );
      return;
    }
    setConnectorPolicyField(toolName, "disabled_tools", [
      ...draft.disabled_tools,
      disabledToolName,
    ]);
  };

  return {
    getConnectorDraft,
    getConnectorPolicyDraft,
    setConnectorField,
    setConnectorPolicyField,
    addConnectorExtraTool,
    removeConnectorExtraTool,
    toggleConnectorDisabledTool,
  };
}
