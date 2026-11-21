import { FormEvent, useCallback, useEffect, useState, type Dispatch, type SetStateAction } from "react";
import type { ReadJsonFn } from "../hooks/useAdminTabLoader.types";
import { LoadingState } from "../../layout/LoadingState";

type PersonalityPayload = {
  id: string;
  user_id: string;
  language: string;
  detail_level: string;
  communication_style: string;
  output_format: string;
  custom_prompt: string | null;
  timezone: string;
  created_at: string;
  updated_at: string;
};

type PersonalityFormState = {
  language: string;
  detail_level: string;
  communication_style: string;
  output_format: string;
  custom_prompt: string;
  timezone: string;
};

type AdminPersonalityTabProps = {
  readJson: ReadJsonFn;
};

const LANGUAGE_OPTIONS = ["en", "de", "fr", "es", "it"] as const;
const DETAIL_LEVEL_OPTIONS = ["concise", "standard", "detailed"] as const;
const COMMUNICATION_STYLE_OPTIONS = [
  "technical",
  "concise",
  "friendly",
  "formal",
] as const;
const OUTPUT_FORMAT_OPTIONS = ["full", "bullets", "summary", "json"] as const;

type Choice = "language" | "detail_level" | "communication_style" | "output_format";
type SetDraft = Dispatch<SetStateAction<PersonalityFormState>>;

// The four choices, in order; the language explains where it is used.
const CHOICES: Array<{ field: Choice; label: string; options: readonly string[]; help?: string }> = [
  { field: "language", label: "Language", options: LANGUAGE_OPTIONS, help: "Used in prompt scaffolding to enforce response language." },
  { field: "detail_level", label: "Detail level", options: DETAIL_LEVEL_OPTIONS },
  { field: "communication_style", label: "Communication style", options: COMMUNICATION_STYLE_OPTIONS },
  { field: "output_format", label: "Output format", options: OUTPUT_FORMAT_OPTIONS },
];

const DEFAULT_DRAFT: PersonalityFormState = {
  language: "en",
  detail_level: "standard",
  communication_style: "technical",
  output_format: "full",
  custom_prompt: "",
  timezone: "UTC",
};

async function savePersonality(
  readJson: ReadJsonFn, draft: PersonalityFormState, loadPersonality: () => Promise<void>,
  setSaving: Dispatch<SetStateAction<boolean>>, setError: Dispatch<SetStateAction<string | null>>,
  setNotice: Dispatch<SetStateAction<string | null>>,
) {
  setSaving(true);
  setError(null);
  setNotice(null);

  try {
    const payload = {
      language: draft.language || "en",
      detail_level: draft.detail_level || "standard",
      communication_style: draft.communication_style || "technical",
      output_format: draft.output_format || "full",
      custom_prompt: draft.custom_prompt.trim() || null,
      timezone: draft.timezone || "UTC",
    };
    await readJson<PersonalityPayload>("/api/v1/personality", {
      method: "PUT",
      body: JSON.stringify(payload),
    });
    setNotice("Personality saved for this account.");
    await loadPersonality();
  } catch (err) {
    setError(err instanceof Error ? err.message : "Failed to save personality");
  } finally {
    setSaving(false);
  }
}

function usePersonality(readJson: ReadJsonFn) {
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [draft, setDraft] = useState<PersonalityFormState>(DEFAULT_DRAFT);

  const loadPersonality = useCallback(async () => {
    setLoading(true);
    setLoadError(null);
    try {
      const response = await readJson<PersonalityPayload>("/api/v1/personality");
      setDraft({
        language: response.language || "en",
        detail_level: response.detail_level || "standard",
        communication_style: response.communication_style || "technical",
        output_format: response.output_format || "full",
        custom_prompt: response.custom_prompt || "",
        timezone: response.timezone || "UTC",
      });
    } catch (err) {
      setLoadError(err instanceof Error ? err.message : "Failed to load personality");
    } finally {
      setLoading(false);
    }
  }, [readJson]);

  useEffect(() => {
    void loadPersonality();
  }, [loadPersonality]);

  const onSubmit = async (event: FormEvent) => {
    event.preventDefault();
    await savePersonality(readJson, draft, loadPersonality, setSaving, setError, setNotice);
  };
  return { loading, saving, loadError, error, notice, draft, setDraft, onSubmit };
}

function PersonalityChoice({ field, label, options, help, draft, setDraft }: (typeof CHOICES)[number] & {
  draft: PersonalityFormState; setDraft: SetDraft;
}) {
  return (
    <label className="admin-form-field">
      <span className="admin-form-field__label">{label}</span>
      <select
        className="admin-panel__form-input"
        value={draft[field]}
        onChange={(event) =>
          setDraft((value) => ({ ...value, [field]: event.target.value }))
        }
      >
        {options.map((option) => (
          <option key={option} value={option}>
            {option}
          </option>
        ))}
      </select>
      {help ? (
        <span className="admin-form-help">
          {help}
        </span>
      ) : null}
    </label>
  );
}

export function AdminPersonalityTab({ readJson }: AdminPersonalityTabProps) {
  const { loading, saving, loadError, error, notice, draft, setDraft, onSubmit } = usePersonality(readJson);

  if (loading && !loadError) {
    return <LoadingState label="the personality" variant="page" />;
  }

  return (
    <div className="admin-panel__section">
      <div className="admin-panel__section-header">
        <span>LLM Personality</span>
      </div>
      <p className="admin-panel__hint">
        Control language, style, and output behavior used for the current user.
      </p>
      {loadError ? <div className="admin-panel__error">{loadError}</div> : null}
      <form className="admin-form-grid" onSubmit={onSubmit}>
        {CHOICES.map((choice) => <PersonalityChoice key={choice.field} {...choice} draft={draft} setDraft={setDraft} />)}
        <label className="admin-form-field admin-form-field--full">
          <span className="admin-form-field__label">Timezone</span>
          <input
            className="admin-panel__form-input"
            value={draft.timezone}
            onChange={(event) =>
              setDraft((value) => ({ ...value, timezone: event.target.value }))
            }
            placeholder="UTC"
          />
        </label>
        <label className="admin-form-field admin-form-field--full">
          <span className="admin-form-field__label">Custom personality prompt</span>
          <textarea
            className="admin-panel__form-input"
            rows={8}
            value={draft.custom_prompt}
            onChange={(event) =>
              setDraft((value) => ({ ...value, custom_prompt: event.target.value }))
            }
            placeholder="Additional prompt instructions for this account"
          />
          <span className="admin-form-help">
            Optional override text appended to default system prompts.
          </span>
        </label>
        {error ? <div className="admin-panel__error">{error}</div> : null}
        {notice ? <div className="admin-success">{notice}</div> : null}
        <button
          type="submit"
          className="admin-panel__action-btn admin-panel__action-btn--primary"
          disabled={saving || loading}
        >
          {saving ? "Saving…" : "Save personality"}
        </button>
      </form>
    </div>
  );
}
