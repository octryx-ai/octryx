import { useState } from "react";

import { FormSection } from "../../../../layout/FormSection";
import { SidePanel } from "../../../../layout/SidePanel";
import {
  FIELD_LABELS, PROVIDER_TYPE_LABELS, SECRET_FIELDS, deleteModelRoute, saveModelRoute, testModelRoute,
  type ModelRouteDraft, type ModelRoutesPayload, type RouteTestResult,
} from "./modelRoutesApi";

type Props = {
  draft: ModelRouteDraft;
  editing: boolean;
  catalog: ModelRoutesPayload;
  onClose: () => void;
  onChanged: () => void;
};

function testText(result: RouteTestResult): string {
  return result.state === "ok"
    ? `The model answered in ${result.latency_ms} ms.`
    : `The test call failed (${[result.error, result.reason].filter(Boolean).join(", ")}).`;
}

function TextField({ id, label, value, onChange, type = "text", required = false, placeholder }: {
  id: string; label: string; value: string; onChange: (value: string) => void; type?: string; required?: boolean;
  placeholder?: string;
}) {
  return (
    <label className="admin-panel__field" htmlFor={id}>
      <span>{label}{required ? " *" : ""}</span>
      <input id={id} className="admin-panel__input" type={type} value={value} required={required}
        placeholder={placeholder} autoComplete="off" onChange={(event) => onChange(event.target.value)} />
    </label>
  );
}

function ConnectionSection({ draft, editing, catalog, set }: {
  draft: ModelRouteDraft; editing: boolean; catalog: ModelRoutesPayload;
  set: (patch: Partial<ModelRouteDraft>) => void;
}) {
  const spec = catalog.provider_types[draft.provider_type] ?? { fields: [], required: [] };
  return (
    <FormSection title="Connection">
      <label className="admin-panel__field" htmlFor="route-type">
        <span>Provider *</span>
        <select id="route-type" className="admin-panel__input" value={draft.provider_type}
          onChange={(event) => set({ provider_type: event.target.value, credentials: {} })}>
          {Object.keys(catalog.provider_types).map((name) => (
            <option key={name} value={name}>{PROVIDER_TYPE_LABELS[name] ?? name}</option>
          ))}
        </select>
      </label>
      <TextField id="route-model" label="Model ID at the provider" value={draft.model} required
        placeholder="e.g. claude-sonnet-4-5" onChange={(model) => set({ model })} />
      {spec.fields.map((field) => (
        <TextField key={field} id={`route-${field}`} label={FIELD_LABELS[field] ?? field}
          type={SECRET_FIELDS.has(field) ? "password" : "text"}
          required={spec.required.includes(field) && !(editing && SECRET_FIELDS.has(field))}
          placeholder={editing && SECRET_FIELDS.has(field) ? "Unchanged" : undefined}
          value={draft.credentials[field] ?? ""}
          onChange={(value) => set({ credentials: { ...draft.credentials, [field]: value } })} />
      ))}
    </FormSection>
  );
}

function UseSection({ draft, editing, catalog, set }: {
  draft: ModelRouteDraft; editing: boolean; catalog: ModelRoutesPayload;
  set: (patch: Partial<ModelRouteDraft>) => void;
}) {
  return (
    <FormSection title="Use in Octryx">
      {editing ? null : (
        <TextField id="route-alias" label="Model name in Octryx" value={draft.alias} required
          placeholder="e.g. claude-work" onChange={(alias) => set({ alias })} />
      )}
      <label className="admin-panel__field" htmlFor="route-class">
        <span>Data class *</span>
        <select id="route-class" className="admin-panel__input" value={draft.data_policy_class}
          onChange={(event) => set({ data_policy_class: event.target.value })}>
          {catalog.data_policy_classes.map((name) => <option key={name} value={name}>{name}</option>)}
        </select>
      </label>
      <TextField id="route-context" label="Context window (tokens)" type="number" required value={draft.context_limit}
        onChange={(context_limit) => set({ context_limit })} />
      <TextField id="route-input" label="Input price (USD per million tokens)" type="number" required
        value={draft.input_per_million_usd} onChange={(input_per_million_usd) => set({ input_per_million_usd })} />
      <TextField id="route-output" label="Output price (USD per million tokens)" type="number" required
        value={draft.output_per_million_usd} onChange={(output_per_million_usd) => set({ output_per_million_usd })} />
      <label className="admin-panel__checkbox">
        <input type="checkbox" checked={draft.tools} onChange={(event) => set({ tools: event.target.checked })} />
        <span>Calls tools</span>
      </label>
    </FormSection>
  );
}

// New and edit of one model route in the bundled LiteLLM: the connection goes to LiteLLM, the rest to Octryx.
export function ModelRouteDrawer({ draft: initial, editing, catalog, onClose, onChanged }: Props) {
  const [draft, setDraft] = useState(initial);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [tested, setTested] = useState<string | null>(null);
  const set = (patch: Partial<ModelRouteDraft>) => setDraft((current) => ({ ...current, ...patch }));
  const run = async (action: () => Promise<void>) => {
    setBusy(true);
    setError(null);
    try {
      await action();
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : String(failure));
    } finally {
      setBusy(false);
    }
  };
  const save = () => run(async () => {
    await saveModelRoute(draft, editing);
    onChanged();
    onClose();
  });
  const remove = () => run(async () => {
    await deleteModelRoute(draft.alias);
    onChanged();
    onClose();
  });
  const test = () => run(async () => setTested(testText(await testModelRoute(draft.alias))));
  const footer = (
    <>
      {editing ? (
        <>
          <button type="button" className="admin-panel__action-btn" disabled={busy} onClick={remove}
            data-testid="model-route-remove">Remove</button>
          <button type="button" className="admin-panel__action-btn" disabled={busy} onClick={test}
            data-testid="model-route-test">Test</button>
        </>
      ) : null}
      <button type="button" className="admin-panel__action-btn" onClick={onClose}>Cancel</button>
      <button type="submit" form="model-route-form" className="admin-panel__action-btn admin-panel__action-btn--primary"
        disabled={busy} data-testid="model-route-save">
        {busy ? "Saving…" : editing ? "Save changes" : "Add model"}
      </button>
    </>
  );
  return (
    <SidePanel title={editing ? draft.alias : "New model"} subtitle="Bundled LiteLLM" onClose={onClose}
      testId="model-route-panel" footer={footer}>
      <form id="model-route-form" onSubmit={(event) => { event.preventDefault(); void save(); }}>
        <ConnectionSection draft={draft} editing={editing} catalog={catalog} set={set} />
        <UseSection draft={draft} editing={editing} catalog={catalog} set={set} />
        {error ? <p className="admin-panel__form-error" role="alert">{error}</p> : null}
        {tested ? <p className="admin-panel__hint" data-testid="model-route-test-result">{tested}</p> : null}
      </form>
    </SidePanel>
  );
}
