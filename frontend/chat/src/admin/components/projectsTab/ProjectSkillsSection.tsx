import { useCallback, useEffect, useState } from "react";

import { useAdminNavigation } from "../../adminNavigation";
import { loadAssignment, saveAssignment } from "../skillCatalog/skillCatalogApi";
import { SURFACE_LABELS } from "../skillCatalog/skillCatalogTypes";
import { refusalText } from "../skillCatalog/skillCatalogModel";
import type { Assignment, AssignmentPolicy } from "../skillCatalog/skillDeliveryTypes";
import type { Surface } from "../skillCatalog/skillCatalogTypes";
import { draftFrom, isConflict, isDirty, previewCount, saveBody, setSurface } from "../skillCatalog/workspaceSkillsModel";
import { WorkspaceEffectiveSkills } from "./WorkspaceEffectiveSkills";
import { WorkspaceSkillsPicker } from "./WorkspaceSkillsPicker";
import "../policyEngine/policiesPage.css";
import "../skillCatalog/skillsPage.css";
import "../skillCatalog/skillTabs.css";

const SURFACE_HINTS: Record<Surface, string> = {
  platform_chat: "Agents in this Workspace can search and load assigned skills.",
  octryx_claude: "Assigned skills are delivered to Claude Code sessions started for this Workspace (refreshed at every start).",
};

// Workspace settings → Skills (WP 2.7, mock `#screen-workspace`): which catalog skills this Workspace gets
// (all published, selected categories and skills, or none; blocked always wins), on which surfaces, and the
// effective set the server computes with each skill's readiness. Edits stay local until Save, which sends the whole
// state with If-Match on the loaded digest; a concurrent save (409 skill_assignment_conflict) reloads the view.
export function ProjectSkillsSection({ ctx }: { ctx: Record<string, unknown> }) {
  const { configuringProjectQuality } = ctx as { configuringProjectQuality?: { id: string; name: string } };
  const projectId = configuringProjectQuality?.id || "";
  const { openAdminTab } = useAdminNavigation();
  const [view, setView] = useState<Assignment | null>(null);
  const [draft, setDraft] = useState<AssignmentPolicy | null>(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<{ text: string; problem: boolean } | null>(null);

  const show = (next: Assignment) => {
    setView(next);
    setDraft(draftFrom(next.policy));
  };

  const load = useCallback(async () => {
    if (!projectId) return;
    const next = (await loadAssignment(projectId)) as Assignment;
    setView(next);
    setDraft(draftFrom(next.policy));
  }, [projectId]);

  useEffect(() => {
    load().catch((error) => setMessage({ text: refusalText(error), problem: true }));
  }, [load]);

  const save = () => saveWorkspaceSkills({ projectId, view, draft, show, load, setBusy, setMessage });

  const dirty = Boolean(view && draft && isDirty(draft, view.policy));

  return (
    <section className="admin-panel__stack skills" data-testid="workspace-skills">
      <div className="admin-panel__section-header">
        <span>Skills</span>
        <button type="button" className="admin-panel__action-btn" data-testid="ws-open-catalog" onClick={() => openAdminTab("skills")}>
          Open skill catalog</button>
      </div>
      {message ? (
        <p className={message.problem ? "workspace-classification__message" : "admin-panel__hint"} role={message.problem ? "alert" : "status"}
          data-testid="ws-message">{message.text}</p>
      ) : null}
      {!view || !draft ? (
        !message?.problem ? <p className="admin-panel__hint" role="status">Loading the Workspace skills…</p> : null
      ) : (
        <WorkspaceSkillsEditor view={view} draft={draft} setDraft={setDraft} busy={busy} dirty={dirty} onSave={() => void save()}
          onDiscard={() => { setDraft(draftFrom(view.policy)); setMessage(null); }} />
      )}
    </section>
  );
}

type Message = { text: string; problem: boolean };

// Saves the whole state on the loaded digest; a concurrent save (409) reloads the view before the refusal is shown.
async function saveWorkspaceSkills({ projectId, view, draft, show, load, setBusy, setMessage }: {
  projectId: string;
  view: Assignment | null;
  draft: AssignmentPolicy | null;
  show: (next: Assignment) => void;
  load: () => Promise<void>;
  setBusy: (busy: boolean) => void;
  setMessage: (message: Message | null) => void;
}) {
  if (!view || !draft) return;
  setBusy(true);
  setMessage(null);
  try {
    show((await saveAssignment(projectId, saveBody(draft), view.digest)) as Assignment);
    setMessage({ text: "Saved. The effective skills below are recomputed.", problem: false });
  } catch (error) {
    if (isConflict(error)) await load().catch(() => undefined);
    setMessage({ text: refusalText(error), problem: true });
  } finally {
    setBusy(false);
  }
}

// What the Workspace gets, on which surfaces, Save / Discard, and the effective set the server computes.
function WorkspaceSkillsEditor({ view, draft, setDraft, busy, dirty, onSave, onDiscard }: {
  view: Assignment;
  draft: AssignmentPolicy;
  setDraft: (draft: AssignmentPolicy) => void;
  busy: boolean;
  dirty: boolean;
  onSave: () => void;
  onDiscard: () => void;
}) {
  return (
    <div className="skills__ws">
      <div className="admin-panel__stack">
        <div className="admin-panel__card">
          <div className="admin-panel__section-header">Which skills this Workspace gets</div>
          <WorkspaceSkillsPicker draft={draft} categories={view.categories} skills={view.skills} disabled={busy} onChange={setDraft} />
        </div>
        <SurfaceToggles draft={draft} setDraft={setDraft} busy={busy} />
        <div className="policies__row">
          <button type="button" className="admin-panel__action-btn admin-panel__action-btn--primary" data-testid="ws-save"
            disabled={busy || !dirty} onClick={onSave}>{busy ? "Saving…" : "Save"}</button>
          <button type="button" className="admin-panel__action-btn" data-testid="ws-discard" disabled={busy || !dirty}
            onClick={onDiscard}>Discard</button>
          {dirty ? <span className="admin-panel__hint">Unsaved changes</span> : null}
        </div>
      </div>
      <div className="admin-panel__stack">
        <WorkspaceEffectiveSkills view={view} dirty={dirty} preview={previewCount(draft, view.skills)} />
      </div>
    </div>
  );
}

function SurfaceToggles({ draft, setDraft, busy }: { draft: AssignmentPolicy; setDraft: (draft: AssignmentPolicy) => void; busy: boolean }) {
  return (
    <div className="admin-panel__card" data-testid="ws-surfaces">
      <div className="admin-panel__section-header">Surfaces in this Workspace</div>
      {(Object.keys(SURFACE_HINTS) as Surface[]).map((surface) => {
        const on = Boolean(draft.surfaces[surface]);
        return (
          <div key={surface} className="skills__toggle">
            <span>{SURFACE_LABELS[surface]}<small>{SURFACE_HINTS[surface]}</small></span>
            <button type="button" role="switch" aria-checked={on} aria-label={SURFACE_LABELS[surface]} disabled={busy}
              className={`skills__switch${on ? " is-on" : ""}`} data-testid={`ws-surface-${surface}`}
              onClick={() => setDraft(setSurface(draft, surface, !on))} />
          </div>
        );
      })}
    </div>
  );
}
