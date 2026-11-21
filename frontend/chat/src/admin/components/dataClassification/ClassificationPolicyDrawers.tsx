// The classification policy page's drawers: add or edit a level, add a rule or read one, a Workspace's overrides
// and one matrix cell. Each saves into the governed draft through `saveDraft`.
import { ClassificationCellDrawer } from "./ClassificationCellDrawer";
import { ClassificationAddLevelDrawer, ClassificationEditLevelDrawer } from "./ClassificationLevelDrawer";
import { ClassificationOverrideDrawer } from "./ClassificationOverrideDrawer";
import { ClassificationAddRuleDrawer, ClassificationRuleDetailDrawer } from "./ClassificationRuleDrawer";
import { type CatalogLevel } from "./classificationLevelCatalog";
import { type EffectRule, effectPolicyText, effectRuleId, effectRuleSentence } from "./classificationEffectsModel";
import { type LevelRules, cellValue, setCell as setMatrixCell } from "./classificationMatrixRows";
import {
  retireClassificationLevel, saveClassificationOverrides, type ClassificationPolicyState, type ClassificationView,
} from "./useClassificationPolicyState";

type SaveDraft = (levels: LevelRules[], defaultLevel: string | null, levelCatalog?: CatalogLevel[], effectRules?: EffectRule[]) => unknown;
type DrawerProps = { state: ClassificationPolicyState; view: ClassificationView; saveDraft: SaveDraft };

function ClassificationLevelDrawers({ state, view, saveDraft }: DrawerProps) {
  const { levelDrawer, setLevelDrawer, rows } = state;
  const { catalog, shown, draftDefault, draftEditable } = view;
  return (
    <>
      {levelDrawer === "add" ? (
        <ClassificationAddLevelDrawer catalog={catalog} levels={shown} rows={rows} onClose={() => setLevelDrawer(null)}
          onSave={({ level, copyFrom }) => {
            setLevelDrawer(null);
            const rules = { ...(shown.find((item) => item.level === copyFrom)?.rules ?? {}) };
            delete rules.allowed_model_aliases;
            void saveDraft([...shown, { level: level.key, rules }], draftDefault, [...catalog, level].sort((a, b) => a.rank - b.rank));
          }} />
      ) : null}
      {levelDrawer && levelDrawer !== "add" && catalog.some((level) => level.key === levelDrawer) ? (
        <ClassificationEditLevelDrawer level={catalog.find((level) => level.key === levelDrawer)!} editable={draftEditable}
          onClose={() => setLevelDrawer(null)}
          onSave={(level) => {
            setLevelDrawer(null);
            void saveDraft(shown, draftDefault, catalog.map((known) => (known.key === level.key ? level : known)));
          }}
          onRetire={() => void retireClassificationLevel(state, view, levelDrawer)} />
      ) : null}
    </>
  );
}

function ClassificationRuleDrawers({ state, view, saveDraft }: DrawerProps) {
  const { ruleDrawer, setRuleDrawer, workspaces } = state;
  const { effects, catalog, shownRules, shown, draftDefault, draftEditable, levelLabel } = view;
  return (
    <>
      {ruleDrawer === "add" && effects ? (
        <ClassificationAddRuleDrawer catalog={effects.catalog} levels={catalog} servers={effects.servers} existing={shownRules}
          workspaceLevels={workspaces?.map((workspace) => workspace.level) ?? null} levelLabel={levelLabel}
          onClose={() => setRuleDrawer(null)}
          onSave={(rule) => { setRuleDrawer(null); void saveDraft(shown, draftDefault, catalog, [...shownRules, rule]); }} />
      ) : null}
      {ruleDrawer && ruleDrawer !== "add" && effects ? (() => {
        const rule = shownRules.find((item) => effectRuleId(item) === ruleDrawer);
        if (!rule) return null;
        const sentence = effectRuleSentence(rule, effects.catalog, levelLabel);
        return (
          <ClassificationRuleDetailDrawer rule={rule} sentence={sentence} policy={effectPolicyText(rule, catalog, sentence)}
            editable={draftEditable} onClose={() => setRuleDrawer(null)}
            onRemove={() => {
              setRuleDrawer(null);
              void saveDraft(shown, draftDefault, catalog, shownRules.filter((item) => effectRuleId(item) !== ruleDrawer));
            }} />
        );
      })() : null}
    </>
  );
}

export function ClassificationPolicyDrawers({ state, view, saveDraft }: DrawerProps) {
  const { overrideFor, setOverrideFor, published, rows, busy, overrideProblem, cell, setCell } = state;
  const { levelLabel, shown, draftEditable, draft, draftDefault } = view;
  return (
    <>
      <ClassificationLevelDrawers state={state} view={view} saveDraft={saveDraft} />
      <ClassificationRuleDrawers state={state} view={view} saveDraft={saveDraft} />
      {overrideFor && overrideFor.level ? (
        <ClassificationOverrideDrawer name={overrideFor.name} levelLabel={levelLabel(overrideFor.level)}
          levelRules={published.find((item) => item.level === overrideFor.level)?.rules} rows={rows}
          overrides={overrideFor.overrides ?? {}} busy={busy} problem={overrideProblem}
          onClose={() => setOverrideFor(null)}
          onSave={(overrides) => saveClassificationOverrides(state, overrideFor, overrides)} />
      ) : null}
      {cell ? (
        <ClassificationCellDrawer row={cell.row} levelKey={cell.level} levelLabel={levelLabel(cell.level)}
          value={cellValue(cell.row, shown.find((item) => item.level === cell.level)?.rules)}
          editable={draftEditable} hasDraft={Boolean(draft)} onClose={() => setCell(null)}
          onSave={(value) => {
            const next = setMatrixCell(shown, cell.level, cell.row, value);
            setCell(null);
            void saveDraft(next, draftDefault);
          }} />
      ) : null}
    </>
  );
}
