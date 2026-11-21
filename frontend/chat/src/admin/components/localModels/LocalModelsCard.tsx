import { useEffect, useState } from "react";

import { readJson } from "../../utils/adminPanelHelpers";
import { ToggleSwitch } from "../settingsKit/SettingsKit";
import {
  LOCAL_MODELS_PATH,
  licenceTag,
  loadOutcome,
  localModelsBody,
  localModelsSaveError,
  readLocalModelsSetting,
  type LocalModelsSetting,
} from "./localModelsModel";

const LABEL = "Only permissive licences for local models (Apache-2.0/MIT)";

/** Admin › Models › Defaults › Local models: the platform's licence switch for launcher-local models. */
export function LocalModelsCard() {
  const [setting, setSetting] = useState<LocalModelsSetting | null>(null);
  const [hidden, setHidden] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let current = true;
    readJson<unknown>(LOCAL_MODELS_PATH).then((payload) => {
      if (!current) return;
      const read = readLocalModelsSetting(payload);
      if (read) setSetting(read); else setProblem("The server's answer was not a local model setting.");
    }).catch((failure: { status?: number }) => {
      if (!current) return;
      if (loadOutcome(failure?.status ?? null) === "hidden") setHidden(true);
      else setProblem("The local model setting could not be loaded.");
    });
    return () => { current = false; };
  }, []);

  if (hidden) return null;
  if (problem) return <section className="admin-panel__card"><p className="sk-err" role="alert">{problem}</p></section>;
  if (!setting) return null;

  const change = async (next: boolean) => {
    setBusy(true);
    setError(null);
    try {
      const response = await fetch(LOCAL_MODELS_PATH, {
        method: "PUT",
        credentials: "same-origin",
        headers: { Accept: "application/json", "Content-Type": "application/json" },
        body: JSON.stringify(localModelsBody(next)),
      });
      let body: unknown = null;
      try { body = await response.json(); } catch { /* keep the status */ }
      const read = response.ok ? readLocalModelsSetting(body) : null;
      if (read) setSetting(read); else setError(localModelsSaveError(response.status, body));
    } catch {
      setError(localModelsSaveError(0, null));
    }
    setBusy(false);
  };

  return (
    <section className="admin-panel__card" aria-label="Local models" data-testid="local-models">
      <div className="admin-panel__section-header"><span>Local models</span></div>
      <div className="sk-trow">
        <div className="sk-trow__txt">
          <div className="sk-name">{LABEL}</div>
          <div className="sk-sub">Some models (e.g. LFM) restrict commercial use above USD 10M revenue.</div>
        </div>
        <ToggleSwitch on={setting.permissiveOnly} label={LABEL} disabled={!setting.canEdit || busy}
          onChange={(next) => void change(next)} testId="local-models-permissive-only" />
      </div>
      <p className="sk-muted">
        {setting.permissiveOnly
          ? "On: devices use only permissively licensed local models. Changes are audited."
          : "Off: a person may load a restricted model only by choosing it explicitly after its licence notice."}
      </p>
      {setting.canEdit ? null : <p className="sk-muted">Read-only: only platform admins can change it.</p>}
      {error ? <p className="sk-err" role="alert" data-testid="local-models-error">{error}</p> : null}
    </section>
  );
}

/** A local model's licence as a quiet tag (link when known, restriction as tooltip). No page lists local models yet. */
export function LicenceTagView({ licence }: { licence: unknown }) {
  const tag = licenceTag(licence);
  const className = `work-badge ${tag.restricted ? "work-badge--attention" : "work-badge--neutral"}`;
  return tag.url ? (
    <a className={className} href={tag.url} target="_blank" rel="noreferrer" title={tag.detail}>{tag.label}</a>
  ) : (
    <span className={className} title={tag.detail}>{tag.label}</span>
  );
}
