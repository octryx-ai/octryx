// The cards of Workspace → Models: which models (with the model table), the defaults and the Claude Code seats.
import type { Dispatch, SetStateAction } from "react";

import { agentsViewHref } from "../../../chat/agents/agentsFocus";
import type { AdminNavigation } from "../../adminNavigation";
import { Checks, LevelTag, OptionCards } from "../settingsKit/SettingsKit";
import type { Contract, WorkspaceModels } from "./workspaceModelsModel";
import {
  SEAT_CARD_LINK_TEXT,
  USED_IN_TEXT,
  companyModelsInSeatText,
  defaultChoices,
  isAllowed,
  seatChecks,
  seatModeText,
  setMode,
  setTaskModel,
  toggleModel,
} from "./workspaceModelsModel";

export type Level = { key: string; label: string; color: string | null };

type CardProps = {
  view: WorkspaceModels;
  draft: Contract;
  setDraft: Dispatch<SetStateAction<Contract | null>>;
  busy: boolean;
  openAdminTab: AdminNavigation["openAdminTab"];
};

// One model: where it can be used, whether it is allowed here, its clearance, approvals and temperature.
function ModelRow({ row, draft, setDraft, busy, levels }: Omit<CardProps, "view" | "openAdminTab"> & {
  row: WorkspaceModels["models"][number];
  levels: Level[];
}) {
  const cleared = levels.find((item) => item.key === row.clearedUpTo);
  return (
    <tr className={row.cleared ? "" : "sk-off"} data-testid={`workspace-model-${row.key}`}>
      <td data-label="Model">
        <div className="sk-name">{row.label}</div>
        <div className="sk-sub">{row.provider}{row.cleared ? "" : ` · not allowed here: ${row.reason}`}</div>
      </td>
      <td data-label="Allowed">
        <label className="admin-panel__checkbox">
          <input type="checkbox" checked={isAllowed(draft, row)} disabled={busy || !row.cleared || draft.mode === "all_cleared"}
            aria-label={`Allow ${row.label}`} data-testid={`workspace-model-allow-${row.key}`}
            onChange={(event) => setDraft(toggleModel(draft, row.key, event.target.checked))} />
        </label>
      </td>
      <td data-label="Used in">
        <span className="sk-chips">{row.usedIn.map((item) => <span key={item} className="admin-policy-chip admin-policy-chip--secondary">{USED_IN_TEXT[item] ?? item}</span>)}</span>
      </td>
      <td data-label="Cleared up to">
        {cleared ? <LevelTag label={cleared.label} color={cleared.color} /> : <span className="admin-panel__cell--muted">{row.clearedUpTo ?? "Not set"}</span>}
      </td>
      <td data-label="Approved for">
        {row.approvedFor.length ? <span className="sk-chips">{row.approvedFor.map((item) => <span key={item} className="admin-policy-chip">{item}</span>)}</span>
          : <span className="admin-panel__cell--muted">–</span>}
      </td>
      <td data-label="Temperature" className="admin-panel__cell--muted">{row.temperature ?? "Model default"}</td>
    </tr>
  );
}

export function ModelsWhichCard({ view, draft, setDraft, busy, openAdminTab, levels, levelLabel, projectId }: CardProps & {
  levels: Level[];
  levelLabel: string;
  projectId: string;
}) {
  return (
    <section className="admin-panel__card" aria-label="Which models">
      <div className="admin-panel__section-header"><span>Which models</span></div>
      <OptionCards name={`models-mode-${projectId}`} label="Which models" value={draft.mode} disabled={busy}
        onChange={(mode) => setDraft(setMode(draft, view.models, mode))}
        options={[
          { value: "all_cleared", title: "All cleared models", desc: "Every model cleared for this Workspace's level, including new ones." },
          { value: "selected", title: "Selected models", desc: "Only the models ticked below." },
        ]} />
      <div className="sk-tabs-scroll">
        <table className="admin-panel__table sk-cards" data-testid="workspace-models-table">
          <thead><tr><th>Model</th><th>Allowed</th><th>Used in</th><th>Cleared up to</th><th>Approved for</th><th>Temperature</th></tr></thead>
          <tbody>
            {view.models.length === 0 ? <tr><td colSpan={6} className="admin-panel__cell--muted">No model is set up on the platform yet.</td></tr> : null}
            {view.models.map((row) => (
              <ModelRow key={row.key} row={row} draft={draft} setDraft={setDraft} busy={busy} levels={levels} />
            ))}
          </tbody>
        </table>
      </div>
      <p className="sk-hint">
        Greyed models are not cleared for <b>{levelLabel}</b>. Clearance, approval and temperature are set per model in{" "}
        <button type="button" className="sk-link" onClick={() => openAdminTab("modelCatalog")}>Runtime → Model catalog</button>.
      </p>
    </section>
  );
}

export function ModelsDefaultsCard({ view, draft, setDraft, busy, openAdminTab }: CardProps) {
  const labelOf = (key: string) => view.models.find((row) => row.key === key)?.label ?? key;
  const choices = defaultChoices(draft, view.models);
  return (
    <section className="admin-panel__card" aria-label="Defaults">
      <div className="admin-panel__section-header"><span>Defaults</span></div>
      <div className="admin-panel__form-grid">
        <label className="admin-panel__field"><span>Default model</span>
          <select value={draft.default ?? ""} disabled={busy} data-testid="workspace-default-model"
            onChange={(event) => setDraft({ ...draft, default: event.target.value || null })}>
            <option value="">Platform default (priority #1)</option>
            {choices.map((row) => <option key={row.key} value={row.key}>{row.label} · {row.provider}</option>)}
          </select>
        </label>
        <div className="admin-panel__field"><span>If a model fails</span>
          <p className="sk-hint">
            The next model <b>allowed here</b> answers, with a notice in the chat. Never a model outside this list.{" "}
            <button type="button" className="sk-link" onClick={() => openAdminTab("modelOrder")}>Runtime → Default &amp; fallback</button>
          </p>
        </div>
      </div>
      <details className="work-detail__section" open={Object.keys(draft.task_overrides).length > 0}>
        <summary className="sk-muted">
          Task models (summaries, memory, extraction) — {Object.keys(draft.task_overrides).length ? "own choice for some tasks" : "platform default"}
        </summary>
        <div className="admin-panel__form-grid" data-testid="workspace-task-models">
          {view.tasks.map((task) => (
            <label key={task.key} className="admin-panel__field">
              <span>{task.label}</span>
              <select value={draft.task_overrides[task.key] ?? ""} disabled={busy} data-testid={`workspace-task-${task.key}`}
                onChange={(event) => setDraft(setTaskModel(draft, task.key, event.target.value))}>
                <option value="">Platform default{task.platformModel ? ` (${labelOf(task.platformModel)})` : ""}</option>
                {defaultChoices(draft, view.models).map((row) => <option key={row.key} value={row.key}>{row.label}</option>)}
              </select>
            </label>
          ))}
        </div>
      </details>
    </section>
  );
}

export function ModelsSeatsCard({ view, draft, projectId, levelLabel }: Pick<CardProps, "view" | "draft"> & {
  projectId: string;
  levelLabel: string;
}) {
  return (
    <section className="admin-panel__card" aria-label="Claude Code seats">
      <div className="admin-panel__section-header"><span>Claude Code seats</span></div>
      {/* The seat card (Agents › Seats & data classification) is the one editor of the seat keys; shown here read-only. */}
      <div className="sk-trow" data-testid="workspace-seat-mode">
        <div className="sk-trow__txt">
          <div className="sk-name">Claude Code seats</div>
          <div className="sk-sub">Members may connect their own Claude Code seat.{" "}
            <a className="sk-link" href={agentsViewHref(projectId, "classification")} data-testid="workspace-seat-mode-link">{SEAT_CARD_LINK_TEXT}</a>
          </div>
        </div>
        <span className="work-badge work-badge--neutral" data-testid="workspace-seat-mode-value">{seatModeText(view.contract.seat.mode)}</span>
      </div>
      <div className="sk-trow" data-testid="workspace-seat-company">
        <div className="sk-trow__txt">
          <div className="sk-name">Offer company models in <span className="admin-policy-inline-code">/model</span></div>
          <div className="sk-sub">Seat sessions also list the allowed company-gateway models. Usage is billed to this Workspace's budget.{" "}
            <a className="sk-link" href={agentsViewHref(projectId, "classification")} data-testid="workspace-seat-company-link">{SEAT_CARD_LINK_TEXT}</a>
          </div>
        </div>
        <span className="work-badge work-badge--neutral" data-testid="workspace-seat-company-value">{companyModelsInSeatText(view.contract.seat.company_models_in_seat)}</span>
      </div>
      <Checks items={seatChecks(view, draft, levelLabel)} testId="workspace-seat-checks" />
    </section>
  );
}
