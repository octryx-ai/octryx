import { SkillEditorChecks, SkillEditorNav } from "./SkillEditorChecks";
import { SkillEditorFields } from "./SkillEditorFields";
import { STATE_LABELS, stateBadge } from "./skillCatalogModel";
import type { CategoryCatalog, SkillVersion } from "./skillCatalogTypes";
import { runSkillEditorSave, useSkillEditor } from "./useSkillEditor";
import type { Loaded } from "./useSkillEditor";
import "./skillEditor.css";

function editorSubtitle(isNew: boolean, frozen: boolean, loaded: Loaded, version: SkillVersion | null): string {
  return isNew
    ? "A new skill starts as draft v1."
    : frozen
      ? `v${version?.version} is in review and frozen; reject it in the review to change it.`
      : loaded.created
        ? `Editing created draft v${version?.version}${version?.base_version ? ` from v${version.base_version}` : ""}.`
        : `Continuing the open draft v${version?.version}.`;
}

// The head: back link, name, state and the save / submit (or, frozen, open review) actions.
function SkillEditorHead({ isNew, name, version, subtitle, frozen, busy, onCancel, onOpenReview, onRun }: {
  isNew: boolean;
  name: string;
  version: SkillVersion | null;
  subtitle: string;
  frozen: boolean;
  busy: boolean;
  onCancel: () => void;
  onOpenReview: () => void;
  onRun: (submit: boolean) => void;
}) {
  const state = version?.state ?? "draft";
  return (
    <div className="skills__detail-head">
      <div>
        <button type="button" className="skills__plain" onClick={onCancel}>← {isNew ? "Skills" : "Skill"}</button>
        <div className="policies__row" style={{ marginTop: ".35rem" }}>
          <span className="skills__detail-name" data-testid="skill-editor-title">{isNew ? "New skill" : name}</span>
          <span className={stateBadge(state)}>{STATE_LABELS[state]}{version ? ` v${version.version}` : ""}</span>
          <span className="skills__hint">{subtitle}</span>
        </div>
      </div>
      <div className="policies__row">
        <button type="button" className="admin-panel__action-btn" onClick={onCancel} disabled={busy}>{frozen ? "Back" : "Cancel"}</button>
        {frozen ? (
          <button type="button" className="admin-panel__action-btn admin-panel__action-btn--primary" data-testid="skill-editor-open-review"
            onClick={onOpenReview}>Open review</button>
        ) : (
          <>
            <button type="button" className="admin-panel__action-btn" data-testid="skill-editor-save" disabled={busy}
              onClick={() => onRun(false)}>{busy ? "Saving…" : "Save draft"}</button>
            <button type="button" className="admin-panel__action-btn admin-panel__action-btn--primary" data-testid="skill-editor-submit"
              disabled={busy} onClick={() => onRun(true)}>Save and submit for review</button>
          </>
        )}
      </div>
    </div>
  );
}

// The full-page skill editor (mock `openEditor` + `editorChecks`): section nav and files left, the form in the
// middle, live spec checks and the SKILL.md preview right. A new skill is created as draft v1; an existing skill
// continues (or starts) its one open draft and saves with If-Match = the digest the editor started from. A draft in
// review is frozen and shown read-only.
export function SkillEditorPage({ skillId, categories, onCancel, onSaved, onOpenReview }: {
  skillId: string | null;
  categories: CategoryCatalog;
  onCancel: () => void;
  onSaved: (skillId: string) => void;
  onOpenReview: (skillId: string) => void;
}) {
  const editor = useSkillEditor(skillId);
  const { isNew, form, loaded, busy, problem, checks, skillMd, patch } = editor;

  if (!loaded) {
    return problem
      ? <p className="workspace-classification__message" role="alert" data-testid="skill-editor-error">{problem}</p>
      : <p className="admin-panel__hint" role="status">Loading the draft…</p>;
  }

  const frozen = loaded.frozen;
  const version = loaded.version;
  const run = (submit: boolean) => runSkillEditorSave(editor, skillId, loaded, submit, { onSaved, onOpenReview });

  return (
    <div data-testid="skill-editor">
      <SkillEditorHead isNew={isNew} name={form.name} version={version} subtitle={editorSubtitle(isNew, frozen, loaded, version)} frozen={frozen}
        busy={busy} onCancel={onCancel} onOpenReview={() => skillId && onOpenReview(skillId)} onRun={(submit) => void run(submit)} />

      {problem ? <p className="policies__warn" role="alert" data-testid="skill-editor-problem" style={{ marginBottom: ".8rem" }}>{problem}</p> : null}
      {frozen ? (
        <p className="policies__note" role="status" data-testid="skill-editor-frozen" style={{ marginBottom: ".8rem" }}>
          This draft is in review: its content is frozen until the review is decided. A rejected draft becomes editable again.
        </p>
      ) : null}

      <div className="skills__editor">
        <SkillEditorNav files={version?.files ?? []} />
        <fieldset className="skills__editor-form" disabled={frozen || busy} data-testid="skill-editor-form">
          <SkillEditorFields form={form} isNew={isNew} licence={version?.licence_spdx ?? "Internal"} categories={categories} onChange={patch} />
        </fieldset>
        <SkillEditorChecks checks={checks} skillMd={skillMd} />
      </div>
    </div>
  );
}
