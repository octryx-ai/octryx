import { useEffect, useState } from "react";
import { readJson } from "../utils/adminPanelHelpers";

import "./presentationFallback.css";

type TemplateState = {
  source: string;
  error_code?: string;
  profile_name?: string;
  template_file: string;
  fallback: { mode: "builtin_neutral" | "disabled"; available: boolean };
};
const endpoint = "/admin/chat/api/panel/office-presentation-fallback";

const MODE_OPTIONS = [
  { value: "builtin_neutral", label: "Neutral presentation template" },
  { value: "disabled", label: "Require a corporate identity template" },
];

// Readable name for what a deck composed now is built from (backend
// presentation_fallback.describe_effective_presentation_template).
function effectiveTemplateLabel(value: TemplateState): string {
  if (value.source === "corp_identity_profile") {
    return `Corporate identity profile: ${value.profile_name || "default profile"}`;
  }
  if (value.source === "builtin_neutral_template") {
    return "Neutral presentation template";
  }
  return "Configuration required: upload a corporate identity template below or allow the neutral template.";
}

export function AdminPresentationFallbackSection() {
  const [value, setValue] = useState<TemplateState | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [draftMode, setDraftMode] = useState<string | null>(null);
  const storedMode = value?.fallback.mode || "disabled";
  const selectedMode = draftMode ?? storedMode;
  useEffect(() => {
    let disposed = false;
    void readJson<TemplateState>(endpoint).then(
      (result) => {
        if (!disposed) setValue(result);
      },
      (failure: Error) => {
        if (!disposed) setError(failure.message);
      },
    );
    return () => {
      disposed = true;
    };
  }, []);
  const save = async (mode: string) => {
    setBusy(true);
    setError("");
    try {
      setValue(
        await readJson<TemplateState>(endpoint, {
          method: "PUT",
          body: JSON.stringify({ mode }),
        }),
      );
      setDraftMode(null);
    } catch (failure) {
      setError(
        failure instanceof Error
          ? failure.message
          : "Setting could not be saved.",
      );
    } finally {
      setBusy(false);
    }
  };
  return (
    <section className="admin-card presentation-fallback" aria-label="Presentation fallback">
      <h3>Presentation template fallback</h3>
      <p className="admin-panel__hint">
        Used for generated decks when no corporate identity profile is set as
        default.
      </p>
      <div className="presentation-fallback__row">
        <label className="presentation-fallback__field">
          <span>Fallback template</span>
          <select
            value={selectedMode}
            disabled={!value || busy}
            onChange={(event) => setDraftMode(event.target.value)}
          >
            {MODE_OPTIONS.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </label>
        <button
          type="button"
          className="admin-panel__action-btn admin-panel__action-btn--primary"
          disabled={!value || busy || selectedMode === storedMode}
          onClick={() => void save(selectedMode)}
        >
          {busy ? "Saving..." : "Save fallback"}
        </button>
      </div>
      {value ? (
        <p className="presentation-fallback__effective">
          Effective template: {effectiveTemplateLabel(value)}
          {value.template_file ? (
            <span className="presentation-fallback__file">{value.template_file}</span>
          ) : null}
        </p>
      ) : null}
      {error ? (
        <p className="admin-panel__form-error" role="alert">
          {error}
        </p>
      ) : null}
    </section>
  );
}
