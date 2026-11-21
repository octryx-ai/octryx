import type { ChangeEvent } from "react";

import type { WorkItem } from "../work/workItemTypes";
import type { WorkRepositoryProfile } from "../work/workCodingPipelineTypes";
import {
  CodingStartActions,
  CodingStartChips,
  CodingStartField,
  CodingStartHeader,
  CodingStartItems,
  CodingStartSource,
} from "./CodingSessionStartParts";
import { submitStartForm, useCodingSessionStartForm } from "./useCodingSessionStartForm";

type CodingSessionStartDialogProps = {
  open: boolean;
  items: WorkItem[];
  repositoryProfiles: WorkRepositoryProfile[];
  onClose: () => void;
  onCreated: (workItemId: string) => void;
};

type TextEvent = ChangeEvent<HTMLInputElement | HTMLTextAreaElement>;
const typed = (setter: (value: string) => void) => (event: TextEvent) => setter(event.target.value);

// The form controls sit directly under the dialog's root, which skins them.
export function CodingSessionStartDialog({ open, items, repositoryProfiles, onClose, onCreated }: CodingSessionStartDialogProps) {
  const form = useCodingSessionStartForm(open, items);
  const { sortedItems, saving, error } = form;
  if (!open) return null;

  return (
    <div className="coding-start" role="dialog" aria-modal="true" aria-labelledby="coding-start-title">
      <div className="coding-start__panel">
        <CodingStartHeader onClose={onClose} />
        <div className="coding-start__body">
          <section className="coding-start__picker" aria-label="Work Item selection">
            <label>
              <span>Work item</span>
              <input value={form.search} onChange={typed(form.setSearch)} placeholder="Search Jira key, title, label, release..."
                disabled={sortedItems.length === 0} />
            </label>
            <CodingStartItems form={form} />
          </section>

          <section className="coding-start__form" aria-label="Coding Session scope">
            <CodingStartSource form={form} />
            <CodingStartField label="Request" hint="What the change plan should achieve. Prefilled from the work item; edit it to narrow the scope.">
              <textarea rows={5} value={form.intent}
                onChange={(event) => { form.setIntentTouched(true); form.setIntent(event.target.value); }} />
            </CodingStartField>
            <div className="coding-start__grid">
              <div className="coding-start__stack">
                <CodingStartField label={<>Repositories<b className="coding-start__required" aria-hidden="true"> *</b></>}
                  hint="One repository per line, named as in the Workspace's repositories.">
                  <textarea rows={4} value={form.repositoryInput} onChange={typed(form.setRepositoryInput)}
                    placeholder={repositoryProfiles[0]?.name || "one repository per line"} />
                </CodingStartField>
                <CodingStartChips form={form} repositoryProfiles={repositoryProfiles} />
              </div>
              <CodingStartField label="Branch hints" hint="Optional. One branch per line, in the same order as the repositories.">
                <textarea rows={4} value={form.branchInput} onChange={typed(form.setBranchInput)} placeholder="optional, one branch per repository" />
              </CodingStartField>
            </div>
            <div className="coding-start__grid">
              <CodingStartField label="Planned files or paths" hint="Optional. Files or folders the change is expected to touch; used to check the scope.">
                <textarea rows={4} value={form.plannedFilesInput} onChange={typed(form.setPlannedFilesInput)} placeholder="optional, one path per line" />
              </CodingStartField>
              <CodingStartField label="Validation commands"
                hint="Commands that prove the change works, e.g. the test command. They become the plan's validation steps.">
                <textarea rows={4} value={form.validationInput} onChange={typed(form.setValidationInput)} placeholder="one command per line" />
              </CodingStartField>
            </div>
            <CodingStartField label="Rollback plan" hint="Optional. How to undo the change; leave empty to generate a default.">
              <input value={form.rollbackPlan} onChange={typed(form.setRollbackPlan)} placeholder="optional; default rollback is generated" />
            </CodingStartField>

            {error ? <div className="work-area__error">{error}</div> : null}
            <CodingStartActions saving={saving} canSubmit={sortedItems.length > 0} onClose={onClose}
              onSubmit={() => submitStartForm(form, onCreated)} />
          </section>
        </div>
      </div>
    </div>
  );
}
