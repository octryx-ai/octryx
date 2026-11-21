import { useAdminNavigation } from "../../adminNavigation";
import type { AdminProjectQuality } from "../../types/projectQualityTypes";
import { LOOKUP_FIELDS } from "./knowledgeLookupModel";
import type { SavedKnowledgeLookupDefaults } from "./knowledgeLookupModel";
import { useKnowledgeLookupDefaults } from "./useKnowledgeLookupDefaults";

type ProjectKnowledgeLookupSectionProps = {
  ctx: Record<string, unknown>;
};

// One number field per limit, with what it changes and its range.
function LookupFieldsCard({ defaults, updateDefault, onOpenKnowledge }: {
  defaults: SavedKnowledgeLookupDefaults;
  updateDefault: (key: keyof SavedKnowledgeLookupDefaults, value: number, min: number, max: number) => void;
  onOpenKnowledge: () => void;
}) {
  return (
    <section className="admin-panel__card">
      <p className="admin-panel__hint" style={{ marginBottom: "1rem" }}>
        How much the knowledge lookup workflow reads per question in this
        workspace. A workflow&apos;s own limits take precedence. The
        knowledge itself lives in the Knowledge area.{" "}
        <button
          type="button"
          className="admin-panel__action-btn"
          onClick={onOpenKnowledge}
        >
          Open Knowledge
        </button>
      </p>
      <div className="admin-form-grid">
        {LOOKUP_FIELDS.map((field) => (
          <label key={field.key} className="admin-form-field">
            <span>{field.label}</span>
            <input
              className="admin-panel__form-input"
              type="number"
              min={field.min}
              max={field.max}
              value={defaults[field.key]}
              onChange={(event) =>
                updateDefault(field.key, Number(event.target.value), field.min, field.max)
              }
            />
            <span className="admin-form-help">
              {field.help} Range {field.min}–{field.max}.
            </span>
          </label>
        ))}
      </div>
    </section>
  );
}

export function ProjectKnowledgeLookupSection({
  ctx,
}: ProjectKnowledgeLookupSectionProps) {
  const { configuringProjectQuality, readJson } = ctx as {
    configuringProjectQuality: AdminProjectQuality | null;
    readJson: <T = unknown>(url: string, init?: RequestInit) => Promise<T>;
  };

  const project = configuringProjectQuality;
  const { openAdminTab } = useAdminNavigation();
  const { defaults, saving, saved, error, handleSave, updateDefault } = useKnowledgeLookupDefaults(project, readJson);


  if (!project) {
    return null;
  }

  return (
    <section className="admin-panel__stack" style={{ marginTop: 20 }}>
      <div className="admin-panel__section-header">
        <div>
          <span>Knowledge lookup limits</span>
        </div>
        <button
          type="button"
          className="admin-panel__action-btn admin-panel__action-btn--primary"
          onClick={() => void handleSave()}
          disabled={saving}
        >
          {saving ? "Saving..." : "Save defaults"}
        </button>
      </div>

      {error ? <div className="admin-panel__error">{error}</div> : null}
      {saved ? (
        <div className="admin-panel__success">Knowledge defaults saved.</div>
      ) : null}

      <LookupFieldsCard defaults={defaults} updateDefault={updateDefault} onOpenKnowledge={() => openAdminTab("knowledgeLibrary")} />
    </section>
  );
}
