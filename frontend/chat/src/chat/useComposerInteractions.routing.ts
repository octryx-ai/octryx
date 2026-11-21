// Composer routing handlers: @-mention agent pick, agent group and agent selection.
import type {
  ComposerInteractionHandlers,
  UseComposerInteractionsArgs,
} from "./useComposerInteractions.types";

export function createComposerRoutingHandlers(args: UseComposerInteractionsArgs): Pick<
  ComposerInteractionHandlers,
  "handleSelectAtAgent" | "handleAgentGroupChange" | "handleAgentSelection"
> {
  const {
    composerValue,
    setComposerValue,
    atMention,
    setAtMention,
    textareaRef,
    agentOptions,
    selectedAgentId,
    setSelectedAgentId,
    setSelectedAgentGroupId,
    setRoutingOverridesEnabled,
  } = args;

  const handleSelectAtAgent = (agent: { id: string; name: string }) => {
    const before = composerValue.slice(0, atMention.startPos);
    const after = composerValue.slice(
      atMention.startPos + 1 + atMention.query.length,
    );
    setComposerValue(`${before}${after}`.trimStart());
    setRoutingOverridesEnabled(true);
    setSelectedAgentId(agent.id);
    const matchingAgent = agentOptions.find((item) => item.id === agent.id);
    setSelectedAgentGroupId(matchingAgent?.groupId || "");
    setAtMention({ open: false, query: "", startPos: -1 });
    textareaRef.current?.focus();
  };

  const handleAgentGroupChange = (nextGroupId: string) => {
    setRoutingOverridesEnabled(true);
    setSelectedAgentGroupId(nextGroupId);
    if (!selectedAgentId) {
      return;
    }
    const nextAgent = agentOptions.find(
      (agent) => agent.id === selectedAgentId,
    );
    if (!nextGroupId || nextAgent?.groupId === nextGroupId) {
      return;
    }
    setSelectedAgentId("");
  };

  const handleAgentSelection = (nextAgentId: string) => {
    setRoutingOverridesEnabled(Boolean(nextAgentId));
    setSelectedAgentId(nextAgentId);
    const nextAgent = agentOptions.find((agent) => agent.id === nextAgentId);
    if (nextAgent?.groupId) {
      setSelectedAgentGroupId(nextAgent.groupId);
    }
  };

  return {
    handleSelectAtAgent,
    handleAgentGroupChange,
    handleAgentSelection,
  };
}
