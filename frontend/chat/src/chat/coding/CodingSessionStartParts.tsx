// Parts of the coding session start dialog. The form controls stay in the dialog itself, under its skinned root;
// these parts hold the header, the item list, the picked item, the field frame, the repository chips and the actions.
import type { ReactNode } from "react";

import type { WorkRepositoryProfile } from "../work/workCodingPipelineTypes";
import { WORK_AREA_HREF } from "./codingQueuePresenter";
import { START_DIALOG_COPY, appendRepository } from "./codingStartCandidates";
import type { CodingSessionStartForm } from "./useCodingSessionStartForm";

const KNOWN_REPOSITORY_LIMIT = 8;

export function CodingStartHeader({ onClose }: { onClose: () => void }) {
  return (
    <header className="coding-start__header">
      <div>
        <div className="work-area__eyebrow">Coding · Step 1: change plan</div>
        <h2 id="coding-start-title">{START_DIALOG_COPY.title}</h2>
        <p className="coding-start__intro">{START_DIALOG_COPY.intro}</p>
      </div>
      <button type="button" className="work-area__button" onClick={onClose}>
        Close
      </button>
    </header>
  );
}

// A labelled field: its name, the control (passed by the dialog) and the hint below it.
export function CodingStartField({ label, hint, children }: { label: ReactNode; hint: string; children: ReactNode }) {
  return (
    <label>
      <span>{label}</span>
      {children}
      <small>{hint}</small>
    </label>
  );
}

export function CodingStartItems({ form }: { form: CodingSessionStartForm }) {
  const { sortedItems, filteredItems, listMessage, selectedItemId } = form;
  return (
    <>
      {listMessage ? (
        <div className="coding-start__empty" role="status">
          <span>{listMessage}</span>
          {sortedItems.length === 0 ? (
            <a className="work-area__button" href={WORK_AREA_HREF}>
              Open Work
            </a>
          ) : null}
        </div>
      ) : null}
      <div className="coding-start__items">
        {filteredItems.map((item) => (
          <button
            key={item.id}
            type="button"
            className={item.id === selectedItemId ? "is-active" : ""}
            onClick={() => {
              form.setSelectedItemId(item.id);
              form.setIntentTouched(false);
            }}
          >
            <strong>{item.source_key}</strong>
            <span>{item.title}</span>
            <small>
              {item.source_status || "no status"} · {item.assignee || "unassigned"}
            </small>
          </button>
        ))}
      </div>
    </>
  );
}

export function CodingStartSource({ form }: { form: CodingSessionStartForm }) {
  const { selectedItem } = form;
  return selectedItem ? (
    <div className="coding-start__source">
      <strong>{selectedItem.source_key}</strong>
      <span>{selectedItem.title}</span>
      <small>
        Jira {selectedItem.source_status || "unknown"} · Work state {selectedItem.work_state} ·{" "}
        {(selectedItem.labels || []).join(", ") || "no labels"}
      </small>
    </div>
  ) : null;
}

type ChipsProps = { form: CodingSessionStartForm; repositoryProfiles: WorkRepositoryProfile[] };

export function CodingStartChips({ form, repositoryProfiles }: ChipsProps) {
  const knownRepositories = repositoryProfiles.slice(0, KNOWN_REPOSITORY_LIMIT);
  return knownRepositories.length > 0 ? (
    <div className="coding-start__chips" aria-label="Known repositories">
      {knownRepositories.map((profile) => (
        <button key={profile.id} type="button"
          onClick={() => form.setRepositoryInput((current) => appendRepository(current, profile.name))}>
          + {profile.name}
        </button>
      ))}
    </div>
  ) : null;
}

type ActionsProps = { saving: boolean; canSubmit: boolean; onClose: () => void; onSubmit: () => void };

export function CodingStartActions({ saving, canSubmit, onClose, onSubmit }: ActionsProps) {
  return (
    <div className="coding-start__actions">
      <button type="button" className="work-area__button" onClick={onClose} disabled={saving}>
        Cancel
      </button>
      <button
        type="button"
        className="work-area__button work-area__button--primary"
        onClick={onSubmit}
        disabled={saving || !canSubmit}
      >
        {saving ? START_DIALOG_COPY.submitting : START_DIALOG_COPY.submit}
      </button>
    </div>
  );
}
