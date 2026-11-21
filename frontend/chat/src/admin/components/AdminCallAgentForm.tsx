// Call agent side panel form: name, channel, model, limits, Teams settings and instructions.
import { FormSection } from "../../layout/FormSection";
import type { RuntimeModelsResponse } from "./callAgentTypes";

export type CallAgentFormFields = {
  formName: string;
  setFormName: (value: string) => void;
  formChannelId: string;
  setFormChannelId: (value: string) => void;
  formLlmModel: string;
  setFormLlmModel: (value: string) => void;
  formMaxToolCalls: number;
  setFormMaxToolCalls: (value: number) => void;
  formCallingWebhookUrl: string;
  setFormCallingWebhookUrl: (value: string) => void;
  formThinkingMessage: string;
  setFormThinkingMessage: (value: string) => void;
  formSystemPrompt: string;
  setFormSystemPrompt: (value: string) => void;
};

type AdminCallAgentFormProps = {
  fields: CallAgentFormFields;
  isEditing: boolean;
  availableChannels: Array<{ id: string; name: string; plugin_id: string }>;
  runtimeModels: RuntimeModelsResponse | null;
};

export function AdminCallAgentForm({ fields, isEditing, availableChannels, runtimeModels }: AdminCallAgentFormProps) {
  const {
    formName, setFormName, formChannelId, setFormChannelId, formLlmModel, setFormLlmModel,
    formMaxToolCalls, setFormMaxToolCalls, formCallingWebhookUrl, setFormCallingWebhookUrl,
    formThinkingMessage, setFormThinkingMessage, formSystemPrompt, setFormSystemPrompt,
  } = fields;
  return (
    <>
      <FormSection title="Call agent">
        <label className="admin-panel__field">
          <span>Name</span>
          <input className="admin-panel__input" type="text" value={formName}
            onChange={(e) => setFormName(e.target.value)} disabled={!isEditing} />
        </label>
        <label className="admin-panel__field">
          <span>Channel (optional)</span>
          <select className="admin-panel__input" value={formChannelId}
            onChange={(e) => setFormChannelId(e.target.value)} disabled={!isEditing}>
            <option value="">No channel (use for all calls)</option>
            {availableChannels.map((ch) => (
              <option key={ch.id} value={ch.id}>
                {ch.name} ({ch.plugin_id})
              </option>
            ))}
          </select>
        </label>
        <label className="admin-panel__field">
          <span>Model</span>
          <select className="admin-panel__input" value={formLlmModel}
            onChange={(e) => setFormLlmModel(e.target.value)} disabled={!isEditing}>
            {runtimeModels && runtimeModels.models.length > 0 ? (
              runtimeModels.models.map((model) => (
                <option key={model.id} value={model.name}>
                  {model.display_name} ({model.provider_name})
                </option>
              ))
            ) : (
              <>
                <option value="claude-sonnet-4-4">Claude Sonnet 4 (default)</option>
                <option value="claude-opus-4-4">Claude Opus 4</option>
                <option value="gpt-4o">GPT-4o</option>
                <option value="gemini-2.0-flash">Gemini 2.0 Flash</option>
              </>
            )}
          </select>
        </label>
        <label className="admin-panel__field">
          <span>Max tool calls</span>
          <input className="admin-panel__input" type="number" min="1" max="20" value={formMaxToolCalls}
            onChange={(e) => setFormMaxToolCalls(parseInt(e.target.value) || 5)} disabled={!isEditing} />
        </label>
      </FormSection>
      <FormSection title="Microsoft Teams">
        <label className="admin-panel__field">
          <span>Calling webhook URL</span>
          <input className="admin-panel__input" type="text" value={formCallingWebhookUrl}
            onChange={(e) => setFormCallingWebhookUrl(e.target.value)} disabled={!isEditing} />
        </label>
        <label className="admin-panel__field">
          <span>Thinking message</span>
          <input className="admin-panel__input" type="text" value={formThinkingMessage}
            onChange={(e) => setFormThinkingMessage(e.target.value)} disabled={!isEditing} />
        </label>
      </FormSection>
      <FormSection title="Instructions">
        <label className="admin-panel__field">
          <span>System prompt</span>
          <textarea className="admin-panel__input" value={formSystemPrompt}
            onChange={(e) => setFormSystemPrompt(e.target.value)} disabled={!isEditing} rows={6} />
        </label>
      </FormSection>
    </>
  );
}
