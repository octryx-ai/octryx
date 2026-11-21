import { useState } from "react";

import { AdminDetailFacts } from "../AdminDetailFacts";
import { ConfirmDialog } from "../confirm/ConfirmDialog";
import { RestDefinitionFields } from "./RestDefinitionFields";
import { updateDefinition, type RestDefinition } from "./restApisApi";
import type { OdataTemplate } from "./restApisApi";
import { ALIAS_NOTE, DEFAULT_PRESET_HINT, DEFAULT_PRESET_OPTIONS, apiTemplate, templateHint } from "./restOdataModel";
import { callsHref } from "./restCallsModel";
import { definitionEditBody, definitionEditDraft, schemeChanged, type DefinitionEditDraft } from "./restDefinitionDraftsModel";
import { fieldError, restErrorView, type RestErrorView } from "./restErrorsModel";
import { schemeLabel } from "./restAuthModel";
import { Field, FormError, Mono } from "./restApisParts";

// The Details tab: what an API is (key, source) stays fixed; name, servers, auth and timeout are edited here and saved
// with PUT /rest-apis/{id}. A changed auth scheme asks first, because the connections may lack the new secret.
export function RestDefinitionDetails({ definition, onSaved }: { definition: RestDefinition; onSaved: (next: RestDefinition) => void }) {
  const [draft, setDraft] = useState<DefinitionEditDraft>(() => definitionEditDraft(definition));
  const [error, setError] = useState<RestErrorView | null>(null);
  const [busy, setBusy] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const operations = definition.operations ?? [];
  const template = apiTemplate(operations);
  const context = { hasWrites: operations.some((op) => !op.is_read), odata: template !== null };
  const dirty = JSON.stringify(draft) !== JSON.stringify(definitionEditDraft(definition));

  const save = async () => {
    setBusy(true);
    setError(null);
    try {
      const next = await updateDefinition(definition.id, definitionEditBody(definition, draft));
      setConfirming(false);
      setDraft(definitionEditDraft(next));
      onSaved(next);
    } catch (failure) {
      setConfirming(false);
      setError(restErrorView(failure));
    } finally {
      setBusy(false);
    }
  };
  const submit = () => (schemeChanged(definition, draft) ? setConfirming(true) : void save());

  return (
    <form className="rst-stack" data-testid="rest-detail-edit" noValidate onSubmit={(event) => { event.preventDefault(); submit(); }}>
      <AdminDetailFacts testId="rest-detail-facts" facts={[
        { label: "Key", value: <Mono>{definition.key}</Mono> },
        { label: "Source", value: definition.source_kind === "openapi" ? `OpenAPI import${definition.spec_version ? ` (${definition.spec_version})` : ""}` : "Entered by hand" },
        { label: "Document URL", value: definition.source_url },
        { label: "Description", value: definition.description },
        { label: "Calls", value: <a className="ds-link-button" href={callsHref(definition.id)} data-testid="rest-def-calls">See the calls of this API ›</a> },
      ]} />
      <Field label="Name" error={fieldError(error, "name")}>
        <input className="admin-panel__input" value={draft.name} onChange={(event) => setDraft({ ...draft, name: event.target.value })}
          data-testid="rest-def-name" />
      </Field>
      {draft.defaultPreset !== undefined ? (
        <Field label="Default template" error={fieldError(error, "default_preset")} testId="rest-def-default-preset"
          hint={`${draft.defaultPreset ? `${templateHint(draft.defaultPreset)} ` : ""}${DEFAULT_PRESET_HINT}${template || draft.defaultPreset ? ` ${ALIAS_NOTE}` : ""}`}>
          <select className="admin-panel__input" value={draft.defaultPreset} data-testid="rest-def-default-preset-select"
            onChange={(event) => setDraft({ ...draft, defaultPreset: event.target.value as OdataTemplate | "" })}>
            {DEFAULT_PRESET_OPTIONS.map((entry) => <option key={entry.value || "none"} value={entry.value}>{entry.label}</option>)}
          </select>
        </Field>
      ) : template ? <p className="rst-muted" data-testid="rest-def-template-note">{`${templateHint(template.value)} Change it per operation under Setup. ${ALIAS_NOTE}`}</p> : null}
      <RestDefinitionFields draft={draft} onChange={setDraft} error={error} context={context} />
      <p className="rst-muted">The secrets themselves belong to each connection.</p>
      <FormError text={error && !error.field ? error.text : null} />
      <div className="rst-row rst-row--end">
        <button type="button" className="ds-btn" disabled={!dirty || busy} onClick={() => { setDraft(definitionEditDraft(definition)); setError(null); }}>
          Discard
        </button>
        <button type="submit" className="ds-btn ds-btn--primary" disabled={!dirty || busy || !draft.name.trim()} data-testid="rest-def-save">
          {busy ? "Saving…" : "Save details"}
        </button>
      </div>
      {confirming ? (
        <ConfirmDialog tone="neutral" title="Change the authentication?" confirmLabel="Change and save" busy={busy}
          onConfirm={() => void save()} onCancel={() => setConfirming(false)}>
          <p>
            {`From ${schemeLabel(definition.auth.scheme)} to ${schemeLabel(draft.scheme)}. Existing connections keep their old secrets and may lack what the new scheme needs; calls through them fail until you set it under Connections.`}
          </p>
        </ConfirmDialog>
      ) : null}
    </form>
  );
}
