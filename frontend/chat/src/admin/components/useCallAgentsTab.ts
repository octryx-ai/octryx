// Admin call agents tab: the Workspace's call agents, the side panel form and their server calls.
import { useEffect, useState } from "react";

import type { CallAgentConfig, RuntimeModelsResponse } from "./callAgentTypes";

const DEFAULT_THINKING_MESSAGE = "Let me check that for you, one moment please.";
const DEFAULT_LLM_MODEL = "claude-sonnet-4-4";

function useCallAgentData() {
  const [selectedProjectId, setSelectedProjectId] = useState<string>("");
  const [configs, setConfigs] = useState<CallAgentConfig[]>([]);
  const [selectedConfig, setSelectedConfig] = useState<CallAgentConfig | null>(
    null,
  );
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [runtimeModels, setRuntimeModels] =
    useState<RuntimeModelsResponse | null>(null);
  const [availableChannels, setAvailableChannels] = useState<
    Array<{ id: string; name: string; plugin_id: string }>
  >([]);
  return {
    selectedProjectId, setSelectedProjectId, configs, setConfigs, selectedConfig, setSelectedConfig,
    loading, setLoading, error, setError, runtimeModels, setRuntimeModels, availableChannels, setAvailableChannels,
  };
}

// Form state for new/edit config
function useCallAgentFormState() {
  const [formName, setFormName] = useState("");
  const [formSystemPrompt, setFormSystemPrompt] = useState("");
  const [formThinkingMessage, setFormThinkingMessage] = useState(DEFAULT_THINKING_MESSAGE);
  const [formLlmModel, setFormLlmModel] = useState(DEFAULT_LLM_MODEL);
  const [formMaxToolCalls, setFormMaxToolCalls] = useState(5);
  const [formChannelId, setFormChannelId] = useState("");
  const [formCallingWebhookUrl, setFormCallingWebhookUrl] = useState("");
  const [isEditing, setIsEditing] = useState(false);
  return {
    formName, setFormName, formSystemPrompt, setFormSystemPrompt, formThinkingMessage, setFormThinkingMessage,
    formLlmModel, setFormLlmModel, formMaxToolCalls, setFormMaxToolCalls, formChannelId, setFormChannelId,
    formCallingWebhookUrl, setFormCallingWebhookUrl, isEditing, setIsEditing,
  };
}

type CallAgentData = ReturnType<typeof useCallAgentData>;
type CallAgentForm = ReturnType<typeof useCallAgentFormState>;

function useCallAgentLoaders(data: CallAgentData) {
  const { selectedProjectId, setRuntimeModels, setAvailableChannels, setConfigs, setSelectedConfig, setLoading, setError } = data;
  // Fetch runtime models when project changes (the setters are stable, so only the project re-runs it)
  useEffect(() => {
    if (!selectedProjectId) {
      setRuntimeModels(null);
      return;
    }
    fetch(`/api/v1/call-agents/runtimes/models?project_id=${selectedProjectId}`)
      .then((r) => r.json())
      .then(setRuntimeModels)
      .catch(() => setRuntimeModels(null));

    // Fetch available channels for this project
    fetch(`/api/v1/channels?project_id=${selectedProjectId}`)
      .then((r) => r.json())
      .then((data) => setAvailableChannels(data.channels || []))
      .catch(() => setAvailableChannels([]));
  }, [selectedProjectId, setRuntimeModels, setAvailableChannels]);

  // Fetch configs when project changes
  useEffect(() => {
    if (!selectedProjectId) {
      setConfigs([]);
      setSelectedConfig(null);
      return;
    }
    setLoading(true);
    fetch(`/api/v1/call-agents/configs?project_id=${selectedProjectId}`)
      .then((r) => r.json())
      .then((data) => {
        setConfigs(data.configs || []);
        setLoading(false);
      })
      .catch(() => {
        setError("Failed to load configs");
        setLoading(false);
      });
  }, [selectedProjectId, setConfigs, setSelectedConfig, setLoading, setError]);
}

function fillForm(form: CallAgentForm, config: CallAgentConfig | null) {
  form.setFormName(config ? config.name : "");
  form.setFormSystemPrompt(config ? config.system_prompt : "");
  form.setFormThinkingMessage(config ? config.thinking_message : DEFAULT_THINKING_MESSAGE);
  form.setFormLlmModel(config ? config.llm_model : DEFAULT_LLM_MODEL);
  form.setFormMaxToolCalls(config ? config.max_tool_calls : 5);
  form.setFormChannelId(config ? config.channel_id || "" : "");
  form.setFormCallingWebhookUrl(config ? (config as any).calling_webhook_url || "" : "");
}

async function saveCallAgent(data: CallAgentData, form: CallAgentForm) {
  const { selectedConfig, selectedProjectId, setConfigs, setSelectedConfig, setError } = data;
  if (!form.formName.trim()) {
    setError("Name is required");
    return;
  }
  setError(null);

  const payload = {
    name: form.formName,
    system_prompt: form.formSystemPrompt,
    thinking_message: form.formThinkingMessage,
    llm_model: form.formLlmModel,
    max_tool_calls: form.formMaxToolCalls,
    channel_id: form.formChannelId || null,
    calling_webhook_url: form.formCallingWebhookUrl || null,
  };
  const init = (method: string) => ({ method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });

  try {
    if (selectedConfig) {
      // Update existing
      const res = await fetch(`/api/v1/call-agents/config/${selectedConfig.id}`, init("PATCH"));
      if (!res.ok) throw new Error("Failed to update");
      const updated = await res.json();
      setConfigs((prev) => prev.map((c) => (c.id === updated.id ? updated : c)));
      setSelectedConfig(updated);
    } else {
      // Create new
      const res = await fetch(
        `/api/v1/call-agents/config?project_id=${selectedProjectId}&name=${encodeURIComponent(form.formName)}`,
        init("POST"),
      );
      if (!res.ok) throw new Error("Failed to create");
      const newConfig = await res.json();
      setConfigs((prev) => [...prev, newConfig]);
      setSelectedConfig(newConfig);
    }
    form.setIsEditing(false);
  } catch (e) {
    setError(e instanceof Error ? e.message : "Save failed");
  }
}

async function deleteCallAgent(data: CallAgentData, configId: string) {
  if (!confirm("Delete this CallAgent?")) return;
  try {
    const res = await fetch(`/api/v1/call-agents/config/${configId}`, {
      method: "DELETE",
    });
    if (!res.ok) throw new Error("Failed to delete");
    data.setConfigs((prev) => prev.filter((c) => c.id !== configId));
    if (data.selectedConfig?.id === configId) {
      data.setSelectedConfig(null);
    }
  } catch (e) {
    data.setError(e instanceof Error ? e.message : "Delete failed");
  }
}

async function testRunCallAgent(data: CallAgentData) {
  if (!data.selectedConfig) return;
  const testMessage = prompt(
    "Enter test message:",
    "Status von Release XYZ?",
  );
  if (!testMessage) return;
  data.setLoading(true);
  try {
    const res = await fetch(
      `/api/v1/call-agents/run?project_id=${encodeURIComponent(data.selectedProjectId)}&user_message=${encodeURIComponent(testMessage)}`,
      { method: "POST" },
    );
    const result = await res.json();
    alert(
      `Response: ${result.final_response}\n\nTools used: ${result.tools_used?.join(", ") || "none"}\n\nError: ${result.error || "none"}`,
    );
  } catch (e) {
    data.setError(e instanceof Error ? e.message : "Test failed");
  } finally {
    data.setLoading(false);
  }
}

export function useCallAgentsTab() {
  const data = useCallAgentData();
  const form = useCallAgentFormState();
  useCallAgentLoaders(data);

  const handleSelectConfig = (config: CallAgentConfig) => {
    data.setSelectedConfig(config);
    fillForm(form, config);
    form.setIsEditing(false);
  };
  const handleNewConfig = () => {
    data.setSelectedConfig(null);
    fillForm(form, null);
    form.setIsEditing(true);
  };
  const closePanel = () => {
    form.setIsEditing(false);
    data.setSelectedConfig(null);
  };
  const cancelEdit = () => {
    form.setIsEditing(false);
    if (data.selectedConfig) handleSelectConfig(data.selectedConfig);
  };
  return {
    data, form, handleSelectConfig, handleNewConfig, closePanel, cancelEdit,
    handleSave: () => saveCallAgent(data, form),
    handleDelete: (configId: string) => deleteCallAgent(data, configId),
    handleTestRun: () => testRunCallAgent(data),
    panelOpen: Boolean(data.selectedConfig) || form.isEditing,
    channelLabel: (channelId: string | null) =>
      channelId ? data.availableChannels.find((channel) => channel.id === channelId)?.name ?? channelId : "All calls",
  };
}

export type CallAgentsTabState = ReturnType<typeof useCallAgentsTab>;
