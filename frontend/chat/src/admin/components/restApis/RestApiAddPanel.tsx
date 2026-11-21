import { useState } from "react";

import { SidePanel } from "../../../layout/SidePanel";
import { StatusLabel } from "../../../layout/StatusLabel";
import { RestDefinitionFields } from "./RestDefinitionFields";
import { createDefinition, importDefinition, updateDefinition, updateOperation, type OdataTemplate, type RestDefinition } from "./restApisApi";
import { ALIAS_NOTE, BATCH_LABEL, CSRF_LABEL, DEFAULT_PRESET_HINT, DEFAULT_PRESET_OPTIONS, ODATA_IMPORT_NOTE, ODATA_TEMPLATES, apiTemplate, isBatch, templateHint, templateLabel } from "./restOdataModel";
import { IMPORTED_OFF } from "./restOperationsModel";
import { emptyManualDraft, importBody, manualBody, type ImportDraft, type ManualDraft } from "./restDefinitionDraftsModel";
import { fieldError, restErrorView, type RestErrorView } from "./restErrorsModel";
import { Field, FormError, Mono, Warnings } from "./restApisParts";

type Mode = "import" | "manual";


// Add a REST API: import its OpenAPI/Swagger description (pasted or from a URL), or enter it by hand. An import shows
// what arrived: every operation off, and the warnings of the reader.
export function RestApiAddPanel({ onClose, onOpen }: { onClose: () => void; onOpen: (id: string) => void }) {
  const [mode, setMode] = useState<Mode>("import");
  const [imp, setImp] = useState<ImportDraft>({ key: "", name: "", source: "text", specText: "", specUrl: "" });
  const [manual, setManual] = useState<ManualDraft>(emptyManualDraft());
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<RestErrorView | null>(null);
  const [imported, setImported] = useState<RestDefinition | null>(null);

  const submit = async () => {
    setBusy(true);
    setError(null);
    try {
      if (mode === "import") setImported(await importDefinition(importBody(imp)));
      else onOpen((await createDefinition(manualBody(manual))).id);
    } catch (failure) {
      setError(restErrorView(failure, mode === "import" ? "import" : "other"));
    } finally {
      setBusy(false);
    }
  };

  if (imported) return <ImportResult imported={imported} onChange={setImported} onOpen={onOpen} />;

  return (
    <SidePanel
      title="Add a REST API"
      onClose={onClose}
      testId="rest-add-panel"
      tabs={{
        tabs: [{ key: "import", label: "Import OpenAPI" }, { key: "manual", label: "Enter by hand" }],
        value: mode, onChange: (next) => { setMode(next as Mode); setError(null); }, label: "How to add", idPrefix: "rest-add",
      }}
      footer={(
        <>
          <button type="button" className="ds-btn" onClick={onClose}>Cancel</button>
          <button type="button" className="ds-btn ds-btn--primary" disabled={busy} onClick={() => void submit()} data-testid="rest-add-submit">
            {busy ? "Adding…" : mode === "import" ? "Import" : "Add REST API"}
          </button>
        </>
      )}
    >
      <form className="rst-stack" onSubmit={(event) => { event.preventDefault(); void submit(); }}>
        <KeyNameFields mode={mode} imp={imp} manual={manual} setImp={setImp} setManual={setManual} error={error} />
        {mode === "import" ? (
          <ImportFields imp={imp} setImp={setImp} error={error} />
        ) : (
          <>
            <RestDefinitionFields draft={manual} onChange={setManual} error={error} />
            <p className="rst-muted">The secrets themselves belong to a connection, which you add after the API.</p>
          </>
        )}
        <FormError text={error && !error.field ? error.text : null} />
      </form>
    </SidePanel>
  );
}

// What an import brought: every operation off, the reader's warnings, the OData template the import set as the API's
// default (backend: collection reads without own settings use it; changed here with one PUT, per operation under
// Setup), $batch operations marked, and the CSRF switch. An answer without `default_preset` sets each read instead.
function ImportResult({ imported, onChange, onOpen }: {
  imported: RestDefinition;
  onChange: (next: RestDefinition) => void;
  onOpen: (id: string) => void;
}) {
  const operations = imported.operations ?? [];
  const hasDefault = imported.default_preset !== undefined;
  const template = hasDefault ? (imported.default_preset ? { value: imported.default_preset } : null) : apiTemplate(operations);
  // Offered while the panel is open once the import detected OData, also after "No template" was chosen.
  const [odata] = useState(() => template !== null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // The API default (PUT /rest-apis/{id} {default_preset}); without `default_preset`: each pre-filled collection read.
  const choose = async (value: OdataTemplate | "") => {
    setBusy(true);
    setError(null);
    try {
      if (hasDefault) {
        onChange(await updateDefinition(imported.id, { default_preset: value }));
      } else if (value) {
        const updated = await Promise.all(operations.map((op) => (op.preset ? updateOperation(imported.id, op.id, { preset: value }) : op)));
        onChange({ ...imported, operations: updated });
      }
    } catch (failure) {
      setError(restErrorView(failure).text);
    } finally {
      setBusy(false);
    }
  };

  return (
      <SidePanel title={`Imported ${imported.name}`} subtitle={`${operations.length} operations · all off`} onClose={() => onOpen(imported.id)}
        testId="rest-import-result"
        footer={<button type="button" className="ds-btn ds-btn--primary" onClick={() => onOpen(imported.id)}
          data-testid="rest-import-open">Open the API</button>}>
        <div className="rst-stack">
          <p className="rst-note">{IMPORTED_OFF}</p>
          <TemplateField hasDefault={hasDefault} odata={odata} template={template} busy={busy} choose={choose} />
          {imported.auth.csrf?.fetch ? <p className="rst-muted" data-testid="rest-import-csrf">{`${CSRF_LABEL}: on, as SAP Gateway needs for writes. Change it under Details.`}</p> : null}
          <FormError text={error} />
          <Warnings items={imported.warnings ?? []} />
          <ul className="rst-card rst-list" data-testid="rest-import-operations">
            {operations.map((op) => (
              <li key={op.id} className="rst-row">
                <span className="rst-method">{op.method}</span>
                <Mono>{op.path}</Mono>
                {op.preset ? <span className="rst-muted">{templateLabel(op.preset)}</span> : null}
                <StatusLabel label={isBatch(op) ? BATCH_LABEL : "Off"} tone="neutral" />
              </li>
            ))}
          </ul>
        </div>
      </SidePanel>
  );
}

// The key (part of every tool name) and the name, for an import or for an API entered by hand.
function KeyNameFields({ mode, imp, manual, setImp, setManual, error }: {
  mode: Mode;
  imp: ImportDraft;
  manual: ManualDraft;
  setImp: (next: ImportDraft) => void;
  setManual: (next: ManualDraft) => void;
  error: RestErrorView | null;
}) {
  const key = (value: string) => (mode === "import" ? setImp({ ...imp, key: value }) : setManual({ ...manual, key: value }));
  return (
    <div className="rst-grid">
      <Field label="Key" hint="Part of every tool name: rest__key__operation." error={fieldError(error, "key")}>
        <input className="admin-panel__input" value={mode === "import" ? imp.key : manual.key} onChange={(event) => key(event.target.value)}
          placeholder="demo_tickets" autoComplete="off" data-testid="rest-add-key" />
      </Field>
      <Field label={mode === "import" ? "Name (optional)" : "Name"}>
        <input className="admin-panel__input" value={mode === "import" ? imp.name : manual.name} placeholder={mode === "import" ? "Taken from the document" : "Demo Tickets"}
          onChange={(event) => (mode === "import" ? setImp({ ...imp, name: event.target.value }) : setManual({ ...manual, name: event.target.value }))} />
      </Field>
    </div>
  );
}

// The document to import: pasted or fetched from a URL, with what an import does.
function ImportFields({ imp, setImp, error }: {
  imp: ImportDraft;
  setImp: (next: ImportDraft) => void;
  error: RestErrorView | null;
}) {
  return (
    <>
      <Field label="Source">
        <select className="admin-panel__input" value={imp.source} onChange={(event) => setImp({ ...imp, source: event.target.value as ImportDraft["source"] })}
          data-testid="rest-add-source">
          <option value="text">Paste the document (JSON or YAML)</option>
          <option value="url">Fetch it from a URL</option>
        </select>
      </Field>
      {imp.source === "text" ? (
        <Field label="OpenAPI 3 or Swagger 2 document" error={fieldError(error, "spec")}>
          <textarea className="admin-panel__input rst-code" value={imp.specText} onChange={(event) => setImp({ ...imp, specText: event.target.value })}
            spellCheck={false} placeholder="openapi: 3.0.3" data-testid="rest-add-spec" />
        </Field>
      ) : (
        <Field label="Document URL" hint="Fetched once through the public web egress." error={fieldError(error, "spec_url") ?? fieldError(error, "spec")}>
          <input className="admin-panel__input" type="url" value={imp.specUrl} onChange={(event) => setImp({ ...imp, specUrl: event.target.value })}
            placeholder="https://api.example.com/openapi.json" />
        </Field>
      )}
      <p className="rst-note">{IMPORTED_OFF}</p>
      <p className="rst-muted">{ODATA_IMPORT_NOTE}</p>
    </>
  );
}

// The OData template the import detected: the API's default, or (no `default_preset`) the template of each collection read.
function TemplateField({ hasDefault, odata, template, busy, choose }: {
  hasDefault: boolean;
  odata: boolean;
  template: { value: OdataTemplate } | null;
  busy: boolean;
  choose: (value: OdataTemplate | "") => Promise<void>;
}) {
  if (hasDefault && odata) {
    return (
      <Field label="Default template" testId="rest-import-template"
        hint={`Detected in the document. ${template ? `${templateHint(template.value)} ` : ""}${DEFAULT_PRESET_HINT} ${ALIAS_NOTE}`}>
        <select className="admin-panel__input" value={template?.value ?? ""} disabled={busy} data-testid="rest-import-template-select"
          onChange={(event) => void choose(event.target.value as OdataTemplate | "")}>
          {DEFAULT_PRESET_OPTIONS.map((entry) => <option key={entry.value || "none"} value={entry.value}>{entry.label}</option>)}
        </select>
      </Field>
    );
  }
  if (!hasDefault && template) {
    return (
      <Field label="OData template of the collection reads" testId="rest-import-template"
        hint={`Detected in the document. ${templateHint(template.value)} ${ALIAS_NOTE}`}>
        <select className="admin-panel__input" value={template.value} disabled={busy} data-testid="rest-import-template-select"
          onChange={(event) => void choose(event.target.value as OdataTemplate)}>
          {ODATA_TEMPLATES.map((entry) => <option key={entry.value} value={entry.value}>{entry.label}</option>)}
        </select>
      </Field>
    );
  }
  return null;
}
