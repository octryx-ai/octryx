import { useEffect, useMemo, useState } from "react";

import { loadPluginSettings, savePluginSettings } from "./pluginUiApi";
import { settingsDraft, settingsErrorText, settingsFields, settingsPayload, type SettingField, type SettingsDraft } from "./pluginSettingsModel";

function shown(field: SettingField): string {
  if (field.control === "secret") return field.secretSet ? "Set" : "Not set";
  if (field.control === "boolean") return field.value === true ? "Yes" : "No";
  return field.value === null || field.value === "" ? "Not set" : String(field.value);
}

// The plugin's settings (contract §4 Settings form), from its JSON schema: who may install it edits, everyone else
// reads. A secret shows only whether it is set; leaving its field empty keeps the stored one.
export function PluginSettingsForm({ installId, canEdit }: { installId: string; canEdit: boolean }) {
  const [fields, setFields] = useState<SettingField[] | null>(null);
  const [draft, setDraft] = useState<SettingsDraft>({});
  const [problems, setProblems] = useState<Record<string, string>>({});
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);
  const [busy, setBusy] = useState(false);

  const apply = (next: SettingField[]) => { setFields(next); setDraft(settingsDraft(next)); };
  useEffect(() => {
    let live = true;
    loadPluginSettings(installId).then(
      (settings) => { if (live) apply(settingsFields(settings.schema, settings.values)); },
      (failure) => { if (live) { setFields([]); setError(settingsErrorText(failure)); } },
    );
    return () => { live = false; };
  }, [installId]);
  const dirty = useMemo(() => fields !== null && JSON.stringify(settingsDraft(fields)) !== JSON.stringify(draft), [fields, draft]);

  if (fields === null) return <p className="plg-muted">Loading settings…</p>;
  if (!fields.length) return error ? <p className="plg-error" role="alert">{error}</p> : <p className="plg-muted">This plugin has no settings.</p>;

  if (!canEdit) {
    return <SettingsFacts fields={fields} />;
  }

  const set = (key: string, value: string | boolean) => { setDraft((current) => ({ ...current, [key]: value })); setSaved(false); };
  const save = async () => {
    const { values, problems: found } = settingsPayload(fields, draft);
    setProblems(found);
    if (Object.keys(found).length) return;
    setBusy(true);
    setError(null);
    try {
      const settings = await savePluginSettings(installId, values);
      apply(settingsFields(settings.schema, settings.values));
      setSaved(true);
    } catch (failure) {
      setError(settingsErrorText(failure));
    } finally {
      setBusy(false);
    }
  };

  return (
    <form className="plg-settings" data-testid="plugin-settings" onSubmit={(event) => { event.preventDefault(); void save(); }}>
      {fields.map((field) => (
        <SettingControl key={field.key} field={field} value={draft[field.key]} problem={problems[field.key]} set={set} />
      ))}
      {error ? <p className="plg-error" role="alert">{error}</p> : null}
      <div className="plg-settings__foot">
        <button type="submit" className="ds-btn ds-btn--primary" disabled={busy || !dirty} data-testid="plugin-settings-save">
          {busy ? "Saving…" : "Save settings"}
        </button>
        {saved && !dirty ? <span className="plg-muted">Saved.</span> : null}
      </div>
    </form>
  );
}

// What a reader sees: each setting with its value (a secret only as Set / Not set).
function SettingsFacts({ fields }: { fields: SettingField[] }) {
  return (
    <dl className="plg-facts" data-testid="plugin-settings">
      {fields.map((field) => [<dt key={`${field.key}-t`}>{field.label}</dt>, <dd key={`${field.key}-v`}>{shown(field)}</dd>])}
    </dl>
  );
}

// One editable setting: a checkbox for a boolean, otherwise a labelled select, password or text / number input.
function SettingControl({ field, value, problem, set }: {
  field: SettingField;
  value: SettingsDraft[string] | undefined;
  problem: string | undefined;
  set: (key: string, value: string | boolean) => void;
}) {
  const label = field.required || /\(optional\)\s*$/i.test(field.label) ? field.label : `${field.label} (optional)`;
  if (field.control === "boolean") {
    return (
      <div className="plg-settings__field">
        <label className="admin-panel__checkbox plg-settings__check">
          <input type="checkbox" checked={value === true} onChange={(event) => set(field.key, event.target.checked)} />
          {field.label}
        </label>
        {field.description ? <span className="plg-muted">{field.description}</span> : null}
      </div>
    );
  }
  return (
    <label className="admin-panel__field plg-settings__field">
      <span>{label}</span>
      {field.control === "enum" ? (
        <select value={String(value ?? "")} onChange={(event) => set(field.key, event.target.value)}>
          {field.required ? null : <option value="">Not set</option>}
          {field.options.map((option) => <option key={option} value={option}>{option}</option>)}
        </select>
      ) : field.control === "secret" ? (
        <span className="plg-settings__secret">
          <input type="password" autoComplete="new-password" value={String(value ?? "")}
            placeholder={field.secretSet ? "Set · type to replace" : "Not set"} onChange={(event) => set(field.key, event.target.value)} />
        </span>
      ) : (
        <input type={field.control === "text" ? "text" : "number"} step={field.control === "integer" ? 1 : "any"}
          value={String(value ?? "")} onChange={(event) => set(field.key, event.target.value)} />
      )}
      {field.description ? <span className="plg-muted">{field.description}</span> : null}
      {problem ? <span className="plg-settings__problem">{problem}</span> : null}
    </label>
  );
}
