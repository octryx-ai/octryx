import {
  CODEX_SEAT_CONDITIONS, CODEX_SEAT_EXPLANATION, CODEX_SEAT_LABEL, codexEngineHint,
} from "./codexSeatModel";
import { SEAT_DEFAULT_HINT, seatStateView } from "./seatStateModel";
import { CLEAR_HINT, canSaveDraft, draftPreview, sourceText } from "./dataClassificationModel";
import { seatSwitchDisabled, seatSwitchNote } from "./dataClassificationSeat";
import type { EffectStatus } from "./dataClassificationModel";
import type { WorkspaceClassification } from "./dataClassificationTypes";
import { SeatPolicySettings } from "./SeatPolicySettings";
import { CodexSeatModels } from "./CodexSeatModels";
import { PLATFORM_ADMIN_HINT, seatBoundLocks, showsPlatformAdminHint } from "./seatPolicyModel";
import { useWorkspaceClassificationCard, type CardMessage } from "./useWorkspaceClassificationCard";
import "./dataClassification.css";
import { SEAT_CARD_LABEL } from "../../../chat/agents/agentsFocus";

// ✓ allowed, ✗ not allowed; "needs configuration" is a neutral state, never ✓.
const STATUS_MARK: Record<EffectStatus, { mark: string; tone: string; words: string }> = {
  allowed: { mark: "✓", tone: "yes", words: "allowed" },
  denied: { mark: "✗", tone: "no", words: "not allowed" },
  needs_configuration: { mark: "–", tone: "pending", words: "needs configuration" },
};

type Card = ReturnType<typeof useWorkspaceClassificationCard>;
type Links = { onOpenPolicy?: () => void; policyHref?: string; onOpenMatrix?: () => void };

function CardLinks({ onOpenPolicy, policyHref, onOpenMatrix }: Links) {
  if (!(onOpenPolicy || policyHref || onOpenMatrix)) return null;
  return (
    <div className="classification-policy__actions" data-testid="classification-links">
      {onOpenPolicy ? <button type="button" className="admin-panel__action-btn" onClick={onOpenPolicy}>See this Workspace's policy</button>
        : policyHref ? <a className="admin-panel__action-btn" href={policyHref}>See this Workspace's policy</a> : null}
      {onOpenMatrix ? (
        <button type="button" className="admin-panel__action-btn" onClick={onOpenMatrix}>What each level allows (classification policy)</button>
      ) : null}
    </div>
  );
}

function CardMessageLine({ message, testId }: { message: CardMessage | null; testId: string }) {
  return message ? <p className={message.ok ? "admin-panel__success" : "workspace-classification__message"} role={message.ok ? "status" : "alert"} data-testid={testId}>{message.text}</p> : null;
}

function ClassificationChoice({ card, model }: { card: Card; model: WorkspaceClassification }) {
  const { draft, setDraft, setMessage, saving } = card;
  const chosen = model.levels.find((level) => level.value === draft);
  return (
    <>
      <label className="admin-panel__field">
        <span>Classification</span>
        <select value={draft} disabled={!model.canEdit || saving} data-testid="classification-select"
          onChange={(event) => { setDraft(event.target.value); setMessage(null); }}>
          <option value="">{draft ? "No classification (clear it)" : "Not set"}</option>
          {model.levels.map((level) => (
            <option key={level.value} value={level.value}>
              {level.description ? `${level.label} — ${level.description}` : level.label}
            </option>
          ))}
        </select>
      </label>
      {chosen?.description ? <p className="admin-panel__hint" data-testid="classification-description">{chosen.description}</p> : null}
      {!draft ? <p className="admin-panel__hint">{CLEAR_HINT}</p> : null}
    </>
  );
}

function ClassificationEffects({ model, draft }: { model: WorkspaceClassification; draft: string }) {
  const preview = draftPreview(model, draft);
  return (
    <div className="workspace-classification__effects" data-testid="classification-effects">
      <p className="workspace-classification__heading">{preview.heading}</p>
      {preview.warning ? <p className="security-field-hint--attention" role="note" data-testid="classification-warning">{preview.warning}</p> : null}
      {preview.lines.length ? (
        <ul className="workspace-classification__lines">
          {preview.lines.map((line) => (
            <li key={line.key} data-allowed={line.allowed ? "yes" : "no"} data-status={line.status}>
              <span className={`workspace-classification__mark workspace-classification__mark--${STATUS_MARK[line.status].tone}`} aria-hidden="true">
                {STATUS_MARK[line.status].mark}
              </span>
              {line.label} {line.words ?? STATUS_MARK[line.status].words}{line.detail ? `: ${line.detail}` : ""}
            </li>
          ))}
        </ul>
      ) : preview.unstated ? <p className="admin-panel__hint">The server did not state what this level allows.</p> : null}
    </div>
  );
}

function ClassificationSave({ card, model }: { card: Card; model: WorkspaceClassification }) {
  const { saving, draft, save, message, seatSettings } = card;
  return (
    <>
      {model.canEdit ? (
        <div>
          <button type="button" className="admin-panel__action-btn admin-panel__action-btn--primary" data-testid="classification-save"
            disabled={saving || !canSaveDraft(model, draft)} onClick={() => void save()}>
            {saving ? "Saving…" : "Save classification"}
          </button>
        </div>
      ) : (
        <p className="admin-panel__hint" data-testid="classification-readonly">Read-only: Workspace admins and owners can change the classification.</p>
      )}
      <CardMessageLine message={message} testId="classification-message" />
      {showsPlatformAdminHint(model.canEdit, seatSettings.canLoosen) ? (
        <p className="admin-panel__hint" role="note" data-testid="seat-bound-hint">{PLATFORM_ADMIN_HINT}</p>
      ) : null}
    </>
  );
}

type SeatView = ReturnType<typeof seatStateView>;
type SeatProps = { card: Card; model: WorkspaceClassification; seat: SeatView; note: string | null; locked: boolean };

function ClaudeSeatSwitch({ card, model, seat, note, locked }: SeatProps) {
  const { saving, toggleSeat, seatMessage } = card;
  return (
    <div className="workspace-classification__seat">
      <label className="admin-panel__checkbox">
        <input type="checkbox" data-testid="seat-toggle" checked={seat.mode === "allowed"}
          disabled={saving || seatSwitchDisabled(model, seat.mode) || locked}
          onChange={(event) => void toggleSeat(event.target.checked)} />
        Allow Claude subscription (seat) sessions
        {seat.mode !== null ? <span className="work-badge work-badge--neutral" data-testid="seat-value">{seat.value}</span> : null}
      </label>
      <p className="admin-panel__hint" data-testid="seat-default-hint">{SEAT_DEFAULT_HINT}</p>
      {note ? <p className="admin-panel__hint" data-testid="seat-block">{note}</p>
        : seat.mode === null ? <p className="admin-panel__hint" data-testid="seat-unknown">The seat setting could not be loaded.</p> : null}
      <CardMessageLine message={seatMessage} testId="seat-message" />
    </div>
  );
}

function CodexSeatSwitch({ card, model, seat, note, locked, projectId }: SeatProps & { projectId: string }) {
  const { saving, toggleCodex, codexMessage, codexEngines, codexModels, seatSettings, load } = card;
  const codexHint = codexEngineHint(codexEngines);
  return (
    <div className="workspace-classification__seat" data-testid="codex-seat">
      <label className="admin-panel__checkbox">
        <input type="checkbox" data-testid="codex-seat-toggle" checked={seat.mode === "allowed"}
          disabled={saving || seatSwitchDisabled(model, seat.mode) || locked}
          onChange={(event) => void toggleCodex(event.target.checked)} />
        {CODEX_SEAT_LABEL}
        <span className="work-badge work-badge--neutral" data-testid="codex-seat-value">{seat.value}</span>
      </label>
      <p className="admin-panel__hint">{CODEX_SEAT_EXPLANATION} {CODEX_SEAT_CONDITIONS}</p>
      {note ? <p className="admin-panel__hint" data-testid="codex-seat-block">{note}</p>
        : seat.mode === null ? <p className="admin-panel__hint" data-testid="codex-seat-unknown">The Codex seat setting could not be loaded.</p> : null}
      {codexHint ? <p className="admin-panel__hint" role="note" data-testid="codex-seat-engine-hint">{codexHint}</p> : null}
      <CardMessageLine message={codexMessage} testId="codex-seat-message" />
      <CodexSeatModels projectId={projectId} view={codexModels} limits={seatSettings.limits} canEdit={model.canEdit}
        canLoosen={seatSettings.canLoosen} busy={saving} onSaved={() => load()} />
    </div>
  );
}

// The Workspace's "Data classification" card: one dropdown with the server's levels in order, what the saved
// (or chosen) level means here, where the value comes from, and the seat switch. Members see it read-only; whether
// the caller may save is the server's answer (`can_edit`), and a refused save shows the server's reason.
// Links to the Workspace's Policy view (a callback inside the Agents area, an address elsewhere) and, for
// platform admins, to the classification policy matrix.
// ``titled``: false where the page itself is called "Data classification" (Agents), so the name is not repeated.
// Loosening a seat bound needs the server's `can_loosen` (seatBoundLocks); tightening stays open.
export function WorkspaceDataClassificationCard({ projectId, onOpenPolicy, policyHref, onOpenMatrix, titled = true }: {
  projectId: string;
  titled?: boolean;
  onOpenPolicy?: () => void;
  policyHref?: string;
  onOpenMatrix?: () => void;
}) {
  const card = useWorkspaceClassificationCard(projectId);
  const { model, problem, draft, seatMode, seatInEffect, seatSet, codex, seatSettings, saving, load } = card;

  if (problem) {
    return <section className="admin-panel__card" aria-label={SEAT_CARD_LABEL}><p className="workspace-classification__message" role="alert" data-testid="classification-error">{problem}</p></section>;
  }
  if (!model) return <p className="admin-panel__hint" role="status">Loading the data classification…</p>;

  // What people see: an unset switch that the default opens (public/internal data) reads and acts as allowed.
  const seat = seatStateView(seatMode, seatInEffect, seatSet.claude);
  const codexSeat = seatStateView(codex.mode, codex.inEffect, seatSet.codex);
  const seatNote = seatSwitchNote(model, seat.mode);
  const codexNote = seatSwitchNote(model, codexSeat.mode);
  const locks = seatBoundLocks(seatSettings.canLoosen, { seatMode: seat.mode, codexMode: codexSeat.mode, requiresGoverned: null, allowsGoverned: null });
  // Locked by the bounds only where the classification itself does not already block or hide the switch.
  const seatLocked = model.canEdit && seat.mode !== null && !seatNote && locks.seatMode;
  const codexLocked = model.canEdit && codexSeat.mode !== null && !codexNote && locks.codexMode;

  return (
    <section className="admin-panel__card workspace-classification" aria-label={SEAT_CARD_LABEL} data-testid="classification-card">
      <div className="admin-panel__section-header">
        {titled ? <span>{SEAT_CARD_LABEL}</span> : <span />}
        <span className="work-badge work-badge--neutral" data-testid="classification-source">{sourceText(model)}</span>
      </div>
      <CardLinks onOpenPolicy={onOpenPolicy} policyHref={policyHref} onOpenMatrix={onOpenMatrix} />
      <ClassificationChoice card={card} model={model} />
      <ClassificationEffects model={model} draft={draft} />
      <ClassificationSave card={card} model={model} />
      <ClaudeSeatSwitch card={card} model={model} seat={seat} note={seatNote} locked={seatLocked} />
      <CodexSeatSwitch card={card} model={model} seat={codexSeat} note={codexNote} locked={codexLocked} projectId={projectId} />
      <SeatPolicySettings projectId={projectId} model={model} settings={seatSettings} busy={saving} onSaved={() => load()} />
    </section>
  );
}
