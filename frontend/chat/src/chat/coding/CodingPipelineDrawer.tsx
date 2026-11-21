import { useState } from "react";

import { saveCodingPipeline } from "../work/workCodingApi";
import { hasJsonErrors, listHasValue, toggleListValue } from "./codingGovernanceForm";
import { AdvancedJson, DrawerSection, GovernanceDrawer } from "./CodingGovernanceKit";
import { CheckboxField, JsonField, KnownValues, TextField } from "./codingGovernanceFields";
import { PIPELINE_JSON_HELP, pipelineFormToPayload, pipelineStageRows, type PipelineForm } from "./codingPipelineForm";

export function CodingPipelineDrawer({
  initial,
  reviewStatusOptions,
  onClose,
  onSaved,
}: {
  initial: PipelineForm;
  reviewStatusOptions: string[];
  onClose: () => void;
  onSaved: () => void;
}) {
  const [form, setForm] = useState<PipelineForm>(initial);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const update = (patch: Partial<PipelineForm>) => setForm((current) => ({ ...current, ...patch }));
  const jsonInvalid = hasJsonErrors([
    [form.stages, "objectList"],
    [form.controls, "object"],
  ]);
  const stages = pipelineStageRows(form.stages);

  async function save() {
    if (!form.name.trim()) {
      setError("Give the pipeline a name.");
      return;
    }
    if (jsonInvalid) {
      setError("Fix the highlighted fields under Advanced (JSON) before saving.");
      return;
    }
    setSaving(true);
    setError(null);
    try {
      await saveCodingPipeline(pipelineFormToPayload(form));
      onSaved();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to save coding pipeline");
    } finally {
      setSaving(false);
    }
  }

  return (
    <GovernanceDrawer
      eyebrow={form.id ? "Edit pipeline" : "New pipeline"}
      title={form.name || "Coding pipeline"}
      submitLabel={form.id ? "Save pipeline" : "Create pipeline"}
      saving={saving}
      error={error}
      dirty={form !== initial}
      onSubmit={() => void save()}
      onClose={onClose}
    >
      <DrawerSection>
        <TextField label="Name" value={form.name} onChange={(name) => update({ name })} required />
        <TextField label="Description" value={form.description} onChange={(description) => update({ description })} multiline />
        <TextField
          label="Review status"
          value={form.review_status}
          onChange={(review_status) => update({ review_status })}
          listId="coding-pipeline-review-status"
          help="Your team's review state for this pipeline. Stored as text; new pipelines start as needs_review."
        />
        <KnownValues id="coding-pipeline-review-status" values={reviewStatusOptions} />
        <CheckboxField label="Active" checked={form.is_active} onChange={(is_active) => update({ is_active })}
          help="A pipeline run without an explicit pipeline uses the most recently updated active one." />
      </DrawerSection>
      <DrawerSection title="Steps">
        {stages ? (
          <ol className="coding-gov-steps">
            {stages.map((stage) => (
              <li key={stage.key}>
                <CheckboxField
                  label={stage.label}
                  checked={listHasValue(form.required_stage_keys, stage.key)}
                  onChange={(checked) => update({ required_stage_keys: toggleListValue(form.required_stage_keys, stage.key, checked) })}
                />
              </li>
            ))}
          </ol>
        ) : (
          <p className="coding-gov-error">The steps cannot be shown until the stages JSON under Advanced (JSON) is fixed.</p>
        )}
        <p className="coding-gov-help">Checked steps are saved as the pipeline's required steps. Add, remove or reorder steps in the stages JSON.</p>
      </DrawerSection>
      <DrawerSection>
        <AdvancedJson hasError={jsonInvalid} intro="The step definitions and run controls behind the form. Leave the defaults if unsure.">
          <JsonField label="Stages" help={PIPELINE_JSON_HELP.stages} kind="objectList" value={form.stages}
            onChange={(stagesText) => update({ stages: stagesText })} />
          <JsonField label="Controls" help={PIPELINE_JSON_HELP.controls} kind="object" value={form.controls}
            onChange={(controls) => update({ controls })} />
        </AdvancedJson>
      </DrawerSection>
    </GovernanceDrawer>
  );
}
