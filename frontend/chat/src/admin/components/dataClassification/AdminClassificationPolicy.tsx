import { SubTabs } from "../settingsKit/SettingsKit";
import "../settingsKit/settingsKit.css";
import { ClassificationChangesTab } from "./ClassificationChangesTab";
import { ClassificationDraftBar } from "./ClassificationDraftBar";
import { ClassificationHeader } from "./ClassificationHeader";
import { ClassificationMatrix } from "./ClassificationMatrix";
import { ClassificationPolicyDrawers } from "./ClassificationPolicyDrawers";
import { ClassificationWorkspacesTab } from "./ClassificationWorkspacesTab";
import { type CatalogLevel } from "./classificationLevelCatalog";
import { type EffectRule } from "./classificationEffectsModel";
import { type LevelRules } from "./classificationMatrixRows";
import { overrideChips } from "./classificationOverridesModel";
import { INVALID_STATE_TEXT } from "./classificationPolicyModel";
import type { ClassificationPolicy } from "./classificationPolicyModel";
import {
  decideClassificationVersion,
  discardClassificationDraft,
  loadInstanceDefault,
  saveClassificationDraft,
  saveWorkspaceClassification,
  submitClassificationDraft,
} from "./dataClassificationApi";
import { readInstanceDefault } from "./dataClassificationModel";
import "./dataClassification.css";
import {
  classificationRunner, classificationView, effectExtraRows, useClassificationPolicyState, type ClassificationPolicyState,
  type ClassificationTab, type ClassificationView,
} from "./useClassificationPolicyState";
import { useAdminNavigation } from "../../adminNavigation";
import { SEAT_CARD_LABEL } from "../../../chat/agents/agentsFocus";

const TABS: { id: ClassificationTab; label: string }[] = [
  { id: "matrix", label: "Levels & rules" },
  { id: "workspaces", label: "Workspaces" },
  { id: "changes", label: "Changes" },
];

type Run = ReturnType<typeof classificationRunner>;
type SectionProps = { state: ClassificationPolicyState; view: ClassificationView; policy: ClassificationPolicy; run: Run };

// The default level for new Workspaces and the draft's review bar (editors only).
function ClassificationDraftControls({ state, view, policy, run, saveDraft }: SectionProps & {
  saveDraft: (levels: LevelRules[], defaultLevel: string | null) => unknown;
}) {
  const { instanceDefault, engineMode, busy, versions, setTab, load, setWorkspaces } = state;
  const { editable, draftDefault, publishedDefault, draftEditable, shown, draft } = view;
  const afterPublish = async () => { await load(); setWorkspaces(null); };
  return (
    <>
      {editable ? (
        <ClassificationHeader levels={instanceDefault?.levels ?? policy.levels.map((level) => ({ value: level.level, label: level.label, description: "", effects: null }))}
          defaultLevel={draftDefault} publishedDefault={publishedDefault} unclassified={instanceDefault?.unclassifiedWorkspaces ?? null}
          engineMode={engineMode} editable={draftEditable} busy={busy}
          onDefaultLevel={(level) => void saveDraft(shown, level)}
          onApplyDefault={() => void setTab("workspaces")} />
      ) : null}
      {editable && versions ? (
        <ClassificationDraftBar view={versions} busy={busy} onReview={() => setTab("changes")}
          onSubmit={() => void run(() => submitClassificationDraft(null), "Submitted for review.")}
          onDiscard={() => void run(() => discardClassificationDraft(), draft?.state === "in_review" ? "Review withdrawn." : "Draft discarded.")}
          onApprove={() => void run(() => decideClassificationVersion(draft!.version, "approve"), "Published.").then((ok) => { if (ok) void afterPublish(); })}
          onReject={() => void run(() => decideClassificationVersion(draft!.version, "reject"), "Sent back to the author.")} />
      ) : null}
    </>
  );
}

// "Levels & rules": add a level or rule, the matrix, and the way to a Workspace's seats.
function ClassificationMatrixSection({ state, view, openAdminTab }: {
  state: ClassificationPolicyState;
  view: ClassificationView;
  openAdminTab: ReturnType<typeof useAdminNavigation>["openAdminTab"];
}) {
  const { setLevelDrawer, setRuleDrawer, rows, published, setCell } = state;
  const { draftEditable, matrixLevels, shown } = view;
  return (
    <div className="sk-page">
      <div className="sk-between">
        <span />
        {draftEditable ? (
          <div className="sk-row">
            <button type="button" className="admin-panel__action-btn" data-testid="classification-add-level" onClick={() => setLevelDrawer("add")}>
              Add level
            </button>
            <button type="button" className="admin-panel__action-btn admin-panel__action-btn--primary" data-testid="classification-add-rule"
              onClick={() => setRuleDrawer("add")}>
              Add rule
            </button>
          </div>
        ) : null}
      </div>
      <ClassificationMatrix levels={matrixLevels} rows={rows} rules={shown} published={published}
        onCell={(level, row) => setCell({ level, row })} onLevel={(level) => setLevelDrawer(level)} extraRows={effectExtraRows(view, setRuleDrawer)} />
      <p className="sk-muted" data-testid="classification-workspace-seats-hint">
        Per-Workspace seats and classification: open a{" "}
        <button type="button" className="sk-link" onClick={() => openAdminTab("projects")}>Workspace</button>
        {" "}› {SEAT_CARD_LABEL}.
      </p>
    </div>
  );
}

// The Workspaces tab (apply the default level, edit overrides) and the Changes tab (versions, roll back).
function ClassificationTabs({ state, view, run }: Omit<SectionProps, "policy">) {
  const { tab, workspaces, busy, rows, setOverrideProblem, setOverrideFor, loadWorkspaces, setInstanceDefault, versions } = state;
  const { editable, levelLabel, levelColor, publishedDefault } = view;
  return (
    <>
      {editable && tab === "workspaces" ? (
        <ClassificationWorkspacesTab workspaces={workspaces} levelLabel={levelLabel} levelColor={levelColor} publishedDefault={publishedDefault}
          editable={editable} busy={busy}
          overrideChips={(workspace) => overrideChips(rows, workspace.overrides ?? {})}
          onEdit={(workspace) => { setOverrideProblem(null); setOverrideFor(workspace); }}
          onApply={(workspaceId) => void run(async () => {
            await saveWorkspaceClassification(workspaceId, publishedDefault);
            await loadWorkspaces();
            const answer = await loadInstanceDefault();
            setInstanceDefault(readInstanceDefault(answer));
            return null;
          }, `${levelLabel(publishedDefault ?? "")} applied.`)} />
      ) : null}
      {editable && versions && tab === "changes" ? (
        <ClassificationChangesTab view={versions} busy={busy}
          onRollback={(version) => void run(() => decideClassificationVersion(version, "rollback"), `Version ${version} restored as a draft.`)} />
      ) : null}
    </>
  );
}

// Settings → Governance → "Classification": the level for new
// Workspaces, the levels × rules matrix, each Workspace's level and the version history. Every change of a platform
// admin goes into the governed draft (draft → review → publish under the approval rule); everybody else reads the
// published policy.
export function AdminClassificationPolicy({ isAdmin = false }: { isAdmin?: boolean }) {
  const { openAdminTab } = useAdminNavigation();
  const state = useClassificationPolicyState(isAdmin);
  const { policy, problem, message, tab, setTab } = state;

  if (problem) return <p className="workspace-classification__message" role="alert" data-testid="policy-error">{problem}</p>;
  if (!policy) return <p className="admin-panel__hint" role="status">Loading the classification policy…</p>;

  const view = classificationView(state, policy);
  const { editable, catalog, shownRules } = view;
  const run = classificationRunner(state);
  const saveDraft = (levels: LevelRules[], defaultLevel: string | null, levelCatalog: CatalogLevel[] = catalog,
    effectRules: EffectRule[] = shownRules) =>
    run(() => saveClassificationDraft({ levels, default_level: defaultLevel, level_catalog: levelCatalog, effect_rules: effectRules }), null);

  return (
    <div className="sk-page" aria-label="Classification" data-testid="classification-policy">
      <ClassificationDraftControls state={state} view={view} policy={policy} run={run} saveDraft={saveDraft} />
      {policy.state === "invalid" ? <p className="workspace-classification__message" role="alert" data-testid="policy-invalid">{INVALID_STATE_TEXT}</p> : null}
      {!policy.canEdit ? <p className="sk-hint" data-testid="policy-readonly">Read-only: platform admins change the classification policy.</p> : null}
      {message ? (
        <p className={message.ok ? "admin-panel__success" : "sk-err"} role={message.ok ? "status" : "alert"} data-testid="policy-message">{message.text}</p>
      ) : null}
      {editable ? <SubTabs value={tab} tabs={TABS} onChange={setTab} label="Classification sections" /> : null}
      {tab === "matrix" || !editable ? <ClassificationMatrixSection state={state} view={view} openAdminTab={openAdminTab} /> : null}
      <ClassificationTabs state={state} view={view} run={run} />
      <ClassificationPolicyDrawers state={state} view={view} saveDraft={saveDraft} />
    </div>
  );
}
