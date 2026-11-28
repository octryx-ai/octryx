import { useEffect, useState } from "react";

import type { AdminProjectQuality } from "../../types/projectQualityTypes";

type ProjectObservabilitySectionProps = {
  ctx: Record<string, unknown>;
};

type ProjectConfig = {
  trace_capture?: { mode?: string };
};

type CaptureMode = "standard" | "minimal";

// A stored debug or audit value stores the same as standard and is shown as standard.
const CAPTURE_MODES: Array<{ value: CaptureMode; label: string; help: string }> = [
  {
    value: "standard",
    label: "Standard",
    help: "Run content (messages, tool calls and results) is stored within the runtime trace limits, so a run can "
      + "be inspected later. After the retention period it is reduced to metadata.",
  },
  {
    value: "minimal",
    label: "Minimal",
    help: "No run content is stored: only model, tokens, cost, outcome, duration and the gate that stopped a run.",
  },
];

function readMode(value: string | undefined): CaptureMode {
  return value === "minimal" ? "minimal" : "standard";
}

export function ProjectObservabilitySection({ ctx }: ProjectObservabilitySectionProps) {
  const { configuringProjectQuality, readJson } = ctx as Record<string, unknown>;
  const project = configuringProjectQuality as AdminProjectQuality | null;
  const [mode, setMode] = useState<CaptureMode>("standard");
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!project?.id || !readJson) return;
    (async () => {
      try {
        const data = await (readJson as (url: string) => Promise<{ config: ProjectConfig }>)(
          `/admin/chat/api/panel/projects/${project.id}/config`,
        );
        setMode(readMode(data.config?.trace_capture?.mode));
      } catch (err) {
        setError(err instanceof Error ? err.message : "Failed to load the capture setting");
      }
    })();
  }, [project?.id, readJson]);

  const handleSave = async () => {
    if (!project?.id || !readJson) return;
    setSaving(true);
    setSaved(false);
    setError(null);
    try {
      await (readJson as (url: string, init?: RequestInit) => Promise<unknown>)(
        `/admin/chat/api/panel/projects/${project.id}/config`,
        { method: "PUT", body: JSON.stringify({ trace_capture: { mode } }) },
      );
      setSaved(true);
      window.setTimeout(() => setSaved(false), 3000);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to save the capture setting");
    } finally {
      setSaving(false);
    }
  };

  if (!project) return null;

  return (
    <div className="admin-panel__stack">
      <div className="admin-panel__section-header">
        <div>
          <span>Run capture</span>
          <p className="admin-panel__hint">
            What a run stores for this Workspace. Secret-like values (passwords, tokens, API keys, known credential
            formats) are redacted before storage in every mode. Admins see run content in Observability → Runs only
            on request, and each view is written to the audit log.
          </p>
        </div>
        <button type="button" className="admin-panel__action-btn admin-panel__action-btn--primary"
          onClick={() => void handleSave()} disabled={saving}>
          {saving ? "Saving..." : "Save"}
        </button>
      </div>

      {error ? <div className="admin-panel__error">{error}</div> : null}
      {saved ? <div className="admin-panel__success">Capture setting saved.</div> : null}

      <section className="admin-panel__card" role="radiogroup" aria-label="Run capture">
        {CAPTURE_MODES.map((option) => (
          <label key={option.value} className="admin-option-card">
            <input type="radio" name={`run-capture-${project.id}`} value={option.value}
              checked={mode === option.value} onChange={() => { setMode(option.value); setSaved(false); }} />
            <span className="admin-option-card__body">
              <span className="admin-option-card__title">{option.label}</span>
              <span className="admin-option-card__desc">{option.help}</span>
            </span>
          </label>
        ))}
      </section>
    </div>
  );
}
