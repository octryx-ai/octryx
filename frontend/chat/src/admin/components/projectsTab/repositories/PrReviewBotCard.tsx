import { useState, type ReactNode } from "react";

import { StatusLabel } from "../../../../layout/StatusLabel";
import { ChipListEditor, OptionCards } from "../../settingsKit/SettingsKit";
import { BRANCHES_HINT, DRAFTS_HINT, TRIGGER_OPTIONS, GATE_HINT, STATUS_OPTIONS } from "./prReviewBotTexts";
import { BOT_STATUS_POLICIES, botControls, botSaveErrors, botSettingsBody, botSettingsProblems, hasBotErrors, providerLabel, readBotSaved, sameBotSettings, syncErrorText, syncResultText, webhookLine, type BotErrors, type BotRepository, type BotSettings, type BotTrigger } from "./prReviewBotModel";
import { BotLimitsFields } from "./BotLimitsFields";
import { call, workspacePath } from "./reviewBotApi";

const repositoryPath = (workspaceId: string, repositoryId: string) =>
  `${workspacePath(workspaceId)}/repositories/${encodeURIComponent(repositoryId)}/pr-review-bot`;

type Note = { tone: "ok" | "err"; text: string };
type Edit = (patch: Partial<BotSettings>) => void;

/** The PUT of one repository's settings: the saved row, or the refusal put at its fields. */
async function saveBotSettings(workspaceId: string, repositoryId: string, sent: BotSettings) {
  const answer = await call(repositoryPath(workspaceId, repositoryId), "PUT", botSettingsBody(sent));
  const saved = answer.ok ? readBotSaved(answer.body) : null;
  return { saved, errors: saved ? null : botSaveErrors(answer.ok ? 500 : answer.status, answer.body, sent) };
}

async function syncBotNow(workspaceId: string, repositoryId: string): Promise<Note> {
  const answer = await call(`${repositoryPath(workspaceId, repositoryId)}/sync`, "POST");
  return answer.ok ? { tone: "ok", text: syncResultText(answer.body) } : { tone: "err", text: syncErrorText(answer.status, answer.body) };
}

type CardProps = {
  workspaceId: string;
  row: BotRepository;
  triggers: BotTrigger[];
  canEdit: boolean;
  webhookConfigured: boolean;
  onSaved: (row: BotRepository, webhookConfigured: boolean | null) => void;
  children?: ReactNode;
};

// One repository's review bot settings: trigger, status policy, drafts, protected branches and limits, with Save and Sync.
export function PrReviewBotCard({ workspaceId, row, triggers, canEdit, webhookConfigured, onSaved, children }: CardProps) {
  const stored = row.settings;
  const [draft, setDraft] = useState(stored);
  const [errors, setErrors] = useState<BotErrors>({});
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState<Note | null>(null);

  const changed = !sameBotSettings(draft, stored);
  const problems = botSettingsProblems(draft);
  const shown: BotErrors = { ...problems, ...errors, branches: { ...(errors.branches ?? {}), ...(problems.branches ?? {}) },
    hotspots: { ...(errors.hotspots ?? {}), ...(problems.hotspots ?? {}) } };
  const controls = botControls(canEdit, stored, changed, busy);
  const edit: Edit = (patch) => { setDraft((current) => ({ ...current, ...patch })); setErrors({}); setNote(null); };
  const testId = `review-bot-${row.id}`;

  async function save() {
    if (hasBotErrors(problems)) return;
    setBusy(true); setErrors({}); setNote(null);
    const { saved, errors: refused } = await saveBotSettings(workspaceId, row.id, draft);
    setBusy(false);
    if (saved) {
      onSaved(saved.row, saved.webhookConfigured);
      setDraft(saved.row.settings);
      setNote({ tone: "ok", text: saved.row.settings.trigger === "off" ? "Saved. The bot is off for this repository." : "Saved." });
    } else if (refused) {
      setErrors(refused);
    }
  }

  async function syncNow() {
    setBusy(true); setNote(null);
    const result = await syncBotNow(workspaceId, row.id);
    setBusy(false);
    setNote(result);
  }

  return (
    <section className="admin-panel__card review-bot__card" aria-label={`PR review bot for ${row.name}`} data-testid="review-bot-repo">
      <BotCardHead row={row} stored={stored} testId={testId} />
      <BotChoiceFields row={row} draft={draft} triggers={triggers} shown={shown} disabled={controls.disabled} testId={testId}
        webhook={webhookLine(draft.trigger, webhookConfigured)} edit={edit} />
      <BotBranchFields row={row} draft={draft} shown={shown} disabled={controls.disabled} testId={testId} edit={edit} />

      <BotLimitsFields draft={draft} errors={shown} disabled={controls.disabled} name={row.name} testId={testId}
        onChange={(patch) => edit(patch)} />

      <BotCardActions controls={controls} busy={busy} blocked={hasBotErrors(problems)} testId={testId} onSync={() => void syncNow()}
        onDiscard={() => { setDraft(stored); setErrors({}); setNote(null); }} onSave={() => void save()} />
      {controls.readOnlyNote ? <p className="sk-muted" data-testid={`${testId}-readonly`}>{controls.readOnlyNote}</p> : null}
      {shown.general ? <p className="sk-err" role="alert">{shown.general}</p> : null}
      {note ? <p className={note.tone === "ok" ? "admin-panel__success" : "sk-err"} role={note.tone === "ok" ? "status" : "alert"}
        data-testid={`${testId}-note`}>{note.text}</p> : null}
      {children}
    </section>
  );
}

function BotCardHead({ row, stored, testId }: { row: BotRepository; stored: BotSettings; testId: string }) {
  const provider = providerLabel(row.repository);
  return (
    <div className="review-bot__head">
      <span className="review-bot__name">{row.name}</span>
      <span className="sk-row">
        {provider ? <StatusLabel label={provider} tone="neutral" /> : null}
        <StatusLabel label={TRIGGER_OPTIONS[stored.trigger].short} tone="neutral" testId={`${testId}-state`} />
      </span>
    </div>
  );
}

type FieldProps = { row: BotRepository; draft: BotSettings; shown: BotErrors; disabled: boolean; testId: string; edit: Edit };

function BotChoiceFields({ row, draft, triggers, shown, disabled, testId, webhook, edit }: FieldProps & {
  triggers: BotTrigger[];
  webhook: ReturnType<typeof webhookLine>;
}) {
  return (
    <>
      <div className="review-bot__field">
        <div className="review-bot__label">Review pull requests</div>
        <OptionCards name={`${testId}-trigger`} label={`Review pull requests of ${row.name}`} value={draft.trigger}
          disabled={disabled} onChange={(trigger) => edit({ trigger })}
          options={triggers.map((trigger) => ({
            value: trigger, title: TRIGGER_OPTIONS[trigger].title, desc: TRIGGER_OPTIONS[trigger].desc,
            badge: TRIGGER_OPTIONS[trigger].recommended ? <StatusLabel label="Recommended" tone="neutral" /> : undefined,
          }))} />
        <p className={webhook.tone === "problem" ? "sk-err" : "sk-muted"} role={webhook.tone === "problem" ? "status" : undefined}
          data-testid={`${testId}-webhook`}>{webhook.text}</p>
        {shown.trigger ? <p className="sk-err" role="alert">{shown.trigger}</p> : null}
      </div>

      <div className="review-bot__field">
        <div className="review-bot__label">Status on the pull request</div>
        <OptionCards name={`${testId}-status`} label={`What the octryx/review status of ${row.name} says`}
          value={draft.statusPolicy} disabled={disabled} onChange={(statusPolicy) => edit({ statusPolicy })}
          options={BOT_STATUS_POLICIES.map((policy) => ({
            value: policy, title: STATUS_OPTIONS[policy].title, desc: STATUS_OPTIONS[policy].desc,
            badge: STATUS_OPTIONS[policy].recommended ? <StatusLabel label="Recommended" tone="neutral" /> : undefined,
          }))} />
        {draft.statusPolicy === "gate" ? <p className="sk-muted" data-testid={`${testId}-gate-hint`}>{GATE_HINT}</p> : null}
        {shown.statusPolicy ? <p className="sk-err" role="alert">{shown.statusPolicy}</p> : null}
      </div>
    </>
  );
}

function BotBranchFields({ row, draft, shown, disabled, testId, edit }: FieldProps) {
  return (
    <>
      <div className="review-bot__field">
        <label className="admin-panel__checkbox">
          <input type="checkbox" checked={draft.reviewDrafts} disabled={disabled} data-testid={`${testId}-drafts`}
            onChange={(event) => edit({ reviewDrafts: event.target.checked })} />
          <span>Review drafts</span>
        </label>
        <p className="sk-muted">{DRAFTS_HINT}</p>
      </div>

      <div className="review-bot__field">
        <div className="review-bot__label">Protected branches</div>
        <ChipListEditor label={`protected branches of ${row.name}`} values={draft.protectedBranches} disabled={disabled}
          testId={`${testId}-branches`} problems={shown.branches} onChange={(protectedBranches) => edit({ protectedBranches })} />
        <p className="sk-muted">{BRANCHES_HINT}</p>
        {shown.protectedBranches ? <p className="sk-err" role="alert">{shown.protectedBranches}</p> : null}
      </div>
    </>
  );
}

function BotCardActions({ controls, busy, blocked, testId, onSync, onDiscard, onSave }: {
  controls: ReturnType<typeof botControls>;
  busy: boolean;
  blocked: boolean;
  testId: string;
  onSync: () => void;
  onDiscard: () => void;
  onSave: () => void;
}) {
  if (!controls.showSave && !controls.showSync) return null;
  return (
    <div className="sk-row review-bot__actions">
      {controls.syncHint ? <span className="sk-muted review-bot__sync-hint" data-testid={`${testId}-sync-hint`}>{controls.syncHint}</span> : null}
      {controls.showSync ? (
        <button type="button" className="admin-panel__action-btn" disabled={controls.syncDisabled}
          title={controls.syncHint ?? undefined} data-testid={`${testId}-sync`} onClick={onSync}>Sync now</button>
      ) : null}
      {controls.showSave ? (
        <>
          <button type="button" className="admin-panel__action-btn" disabled={busy}
            onClick={onDiscard}>Discard</button>
          <button type="button" className="admin-panel__action-btn admin-panel__action-btn--primary" data-testid={`${testId}-save`}
            disabled={busy || blocked} onClick={onSave}>{busy ? "Saving…" : "Save"}</button>
        </>
      ) : null}
    </div>
  );
}
