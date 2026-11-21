import type { FormEvent } from "react";

type ProjectRepoQualityFormProps = {
  projectQualityDraft: string;
  setProjectQualityDraft: (value: string) => void;
  projectQualityError: string | null;
  projectQualityLoading: boolean;
  onSubmit: (event: FormEvent<HTMLFormElement>) => void | Promise<void>;
};

type JsonObject = Record<string, unknown>;

function parseDraft(value: string): JsonObject | null {
  const trimmed = value.trim();
  if (!trimmed) {
    return {};
  }
  try {
    const parsed = JSON.parse(trimmed);
    return parsed && typeof parsed === "object" && !Array.isArray(parsed)
      ? (parsed as JsonObject)
      : null;
  } catch {
    return null;
  }
}

function asObject(value: unknown): JsonObject {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as JsonObject)
    : {};
}

function asString(value: unknown): string {
  return typeof value === "string" ? value : "";
}

function asBoolean(value: unknown): boolean {
  return typeof value === "boolean" ? value : false;
}

function formatList(value: unknown): string {
  return Array.isArray(value)
    ? value
        .map((item) => String(item))
        .filter(Boolean)
        .join(", ")
    : "";
}

function parseList(value: string): string[] {
  return value
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);
}

/** The draft with the default policy patched; empty values drop their key and an empty default drops itself. */
function patchedDraft(parsedDraft: JsonObject, patch: JsonObject): string {
  const nextDefault = { ...asObject(parsedDraft.default), ...patch };
  for (const [key, value] of Object.entries(nextDefault)) {
    if (
      value === "" ||
      value === null ||
      (Array.isArray(value) && value.length === 0)
    ) {
      delete nextDefault[key];
    }
  }
  const nextDraft: JsonObject = { ...parsedDraft, default: nextDefault };
  if (Object.keys(nextDefault).length === 0) {
    delete nextDraft.default;
  }
  return JSON.stringify(nextDraft, null, 2);
}

export function ProjectRepoQualityForm({
  projectQualityDraft,
  setProjectQualityDraft,
  projectQualityError,
  projectQualityLoading,
  onSubmit,
}: ProjectRepoQualityFormProps) {
  const parsedDraft = parseDraft(projectQualityDraft);
  const structuredControlsDisabled = parsedDraft === null;

  const updateDefaultPolicy = (patch: JsonObject) => {
    if (!parsedDraft) {
      return;
    }
    setProjectQualityDraft(patchedDraft(parsedDraft, patch));
  };

  return (
    <form
      className="admin-modal__stack"
      onSubmit={(event) => void onSubmit(event)}
    >
      <div className="admin-panel__section-header">
        <span>Repository quality policy</span>
      </div>
      <p className="admin-panel__hint">
        Configure the default quality toolchain for project repositories. Use
        per-repository overrides only when a repository needs a different setup.
      </p>
      {structuredControlsDisabled ? (
        <div className="admin-panel__form-error">
          Fix the expert JSON before using structured controls.
        </div>
      ) : null}
      <DefaultPolicyFields
        defaultPolicy={asObject(parsedDraft?.default)}
        disabled={structuredControlsDisabled}
        onPatch={updateDefaultPolicy}
      />
      <ExpertJsonField
        value={projectQualityDraft}
        onChange={setProjectQualityDraft}
      />
      {projectQualityError ? (
        <div className="admin-panel__form-error">{projectQualityError}</div>
      ) : null}
      <div className="admin-panel__form-actions">
        <button
          type="submit"
          className="admin-panel__action-btn admin-panel__action-btn--primary"
          disabled={projectQualityLoading}
        >
          {projectQualityLoading ? "Saving…" : "Save Repository Quality"}
        </button>
      </div>
    </form>
  );
}

function ExpertJsonField({
  value,
  onChange,
}: {
  value: string;
  onChange: (value: string) => void;
}) {
  return (
    <details className="admin-modal__stack" style={{ marginTop: 16 }}>
      <summary className="admin-panel__section-header">
        Expert repository quality JSON
      </summary>
      <span className="admin-form-help">
        Supported shape:{" "}
        <code>{'{"default": {...}, "repos": {"repo-name": {...}}}'}</code>
      </span>
      <textarea
        id="project-repo-quality"
        className="connector-field__input connector-field__input--textarea"
        rows={12}
        spellCheck={false}
        value={value}
        onChange={(e) => onChange(e.target.value)}
      />
    </details>
  );
}

function DefaultPolicyFields({
  defaultPolicy,
  disabled,
  onPatch,
}: {
  defaultPolicy: JsonObject;
  disabled: boolean;
  onPatch: (patch: JsonObject) => void;
}) {
  return (
    <div className="admin-form-grid admin-form-grid--dual">
      <label className="admin-form-field">
        <span>Default test command</span>
        <input
          value={asString(defaultPolicy.test_runner)}
          disabled={disabled}
          placeholder="pytest"
          onChange={(event) => onPatch({ test_runner: event.target.value.trim() })}
        />
      </label>
      <label className="admin-form-field">
        <span>Default linter command</span>
        <input
          value={asString(defaultPolicy.linter)}
          disabled={disabled}
          placeholder="ruff check ."
          onChange={(event) => onPatch({ linter: event.target.value.trim() })}
        />
      </label>
      <label className="admin-form-field">
        <span>SAST runners</span>
        <input
          value={formatList(defaultPolicy.sast_runners)}
          disabled={disabled}
          placeholder="semgrep, bandit"
          onChange={(event) => onPatch({ sast_runners: parseList(event.target.value) })}
        />
      </label>
      <label className="admin-checkbox-row">
        <input
          type="checkbox"
          checked={asBoolean(defaultPolicy.requires_baseline_green)}
          disabled={disabled}
          onChange={(event) => onPatch({ requires_baseline_green: event.target.checked })}
        />
        <span>Require green baseline before changes</span>
      </label>
    </div>
  );
}
