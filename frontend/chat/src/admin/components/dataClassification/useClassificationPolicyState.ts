// The classification policy page's state, the view derived from the loaded policy and draft, and its actions: run a
// governed change, save the draft, retire a level and save a Workspace's overrides.
import { useMemo, useState } from "react";

import type { ExtraRow, MatrixLevel } from "./ClassificationMatrix";
import type { ClassifiedWorkspace } from "./ClassificationWorkspacesTab";
import { type CatalogLevel, levelInUseText } from "./classificationLevelCatalog";
import { type EffectRule, effectApplies, effectRuleId, effectTarget } from "./classificationEffectsModel";
import { type LevelRules, type MatrixRow, levelLabelOf, matrixRows } from "./classificationMatrixRows";
import { type VersionsView, readVersions, versionErrorText } from "./classificationVersionsModel";
import type { ClassificationPolicy } from "./classificationPolicyModel";
import { saveClassificationDraft, saveWorkspaceOverrides } from "./dataClassificationApi";
import type { InstanceDefault } from "./dataClassificationTypes";
import { useClassificationPolicyLoad } from "./useClassificationPolicyLoad";

export type ClassificationTab = "matrix" | "workspaces" | "changes";
type Message = { ok: boolean; text: string };

export function useClassificationPolicyState(isAdmin: boolean) {
  const [policy, setPolicy] = useState<ClassificationPolicy | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const [versions, setVersions] = useState<VersionsView | null>(null);
  const [instanceDefault, setInstanceDefault] = useState<InstanceDefault | null>(null);
  const [engineMode, setEngineMode] = useState<string | null>(null);
  const [workspaces, setWorkspaces] = useState<ClassifiedWorkspace[] | null>(null);
  const [tab, setTab] = useState<ClassificationTab>("matrix");
  const [cell, setCell] = useState<{ level: string; row: MatrixRow } | null>(null);
  const [levelDrawer, setLevelDrawer] = useState<"add" | string | null>(null);
  const [ruleDrawer, setRuleDrawer] = useState<"add" | string | null>(null);
  const [overrideFor, setOverrideFor] = useState<ClassifiedWorkspace | null>(null);
  const [overrideProblem, setOverrideProblem] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<Message | null>(null);

  const { load, loadWorkspaces } = useClassificationPolicyLoad({
    isAdmin, tab, ruleDrawer, workspaces, setPolicy, setProblem, setVersions, setInstanceDefault, setEngineMode, setWorkspaces,
  });

  const published: LevelRules[] = useMemo(() => policy?.levels.map((level) => ({ level: level.level, rules: level.rules })) ?? [], [policy]);
  const rows = useMemo(() => matrixRows(policy?.families ?? []), [policy]);
  return {
    policy, problem, versions, setVersions, instanceDefault, setInstanceDefault, engineMode, workspaces, setWorkspaces, tab, setTab,
    cell, setCell, levelDrawer, setLevelDrawer, ruleDrawer, setRuleDrawer, overrideFor, setOverrideFor, overrideProblem,
    setOverrideProblem, busy, setBusy, message, setMessage, load, loadWorkspaces, published, rows,
  };
}

export type ClassificationPolicyState = ReturnType<typeof useClassificationPolicyState>;

// The levels, labels and rules the page shows: the draft's where there is one, else the published policy's.
export function classificationView(state: ClassificationPolicyState, policy: ClassificationPolicy) {
  const { versions, published, instanceDefault } = state;
  const editable = policy.canEdit && versions !== null;
  const draft = versions?.draft ?? null;
  const shown = draft?.levels.length ? draft.levels : published;
  const publishedCatalog: CatalogLevel[] = policy.levels.map((level, index) => ({
    key: level.level, rank: level.info.rank ?? (index + 1) * 100, label: level.label, color: level.info.color ?? "custom",
    description: level.info.description, models_allowed: level.info.modelsAllowed, builtin: level.info.builtin,
  }));
  const catalog = draft?.levelCatalog ?? publishedCatalog;
  const labels = Object.fromEntries(catalog.map((level) => [level.key, level.label]));
  const levelLabel = (key: string) => levelLabelOf(key, labels);
  const levelColor = (key: string) => catalog.find((level) => level.key === key)?.color ?? null;
  const matrixLevels: MatrixLevel[] = catalog.map((level) => ({
    key: level.key, label: level.label, description: level.description, color: level.color,
    draft: !publishedCatalog.some((known) => known.key === level.key),
  }));
  const publishedDefault = instanceDefault?.classification ?? null;
  const draftDefault = draft ? draft.defaultLevel : publishedDefault;
  const draftEditable = editable && draft?.state !== "in_review";
  const effects = versions?.effects;
  const shownRules: EffectRule[] = effects?.draft ?? effects?.published ?? [];
  return {
    editable, draft, shown, catalog, levelLabel, levelColor, matrixLevels, publishedDefault, draftDefault, draftEditable, effects,
    shownRules,
  };
}

export type ClassificationView = ReturnType<typeof classificationView>;

// The matrix rows of the effect rules: a level where the rule applies reads "Off".
export function effectExtraRows({ effects, shownRules, catalog }: ClassificationView, setRuleDrawer: (id: string) => void): ExtraRow[] {
  const publishedRuleIds = new Set((effects?.published ?? []).map(effectRuleId));
  return shownRules.map((rule) => {
    const type = effects?.catalog.find((item) => item.key === rule.effect);
    const target = effectTarget(rule);
    return {
      key: `effect:${effectRuleId(rule)}`,
      label: `${type?.label ?? rule.effect}${target ? ` · ${target}` : ""}`,
      draft: !publishedRuleIds.has(effectRuleId(rule)),
      cell: (levelKey: string) => {
        const level = catalog.find((item) => item.key === levelKey);
        return level && effectApplies(rule, level, catalog) ? { text: "Off", tone: "no" } : { text: "Allowed", tone: "yes" };
      },
      onClick: () => setRuleDrawer(effectRuleId(rule)),
    };
  });
}

// Runs a governed change: the answer's versions replace the view (or the page reloads), with a message.
export function classificationRunner({ setBusy, setMessage, setVersions, load }: ClassificationPolicyState) {
  return async (action: () => Promise<unknown>, done: string | null) => {
    setBusy(true);
    setMessage(null);
    try {
      const answer = await action();
      const read = readVersions(answer);
      if (read) setVersions(read);
      else await load();
      if (done) setMessage({ ok: true, text: done });
      return true;
    } catch (error) {
      setMessage({ ok: false, text: versionErrorText(error) });
      return false;
    } finally {
      setBusy(false);
    }
  };
}

export async function retireClassificationLevel(state: ClassificationPolicyState, view: ClassificationView, key: string) {
  const { setBusy, setMessage, setVersions, setLevelDrawer } = state;
  const { shown, draftDefault, catalog } = view;
  setBusy(true);
  setMessage(null);
  try {
    const answer = await saveClassificationDraft({
      levels: shown.filter((item) => item.level !== key), default_level: draftDefault === key ? null : draftDefault,
      level_catalog: catalog.filter((level) => level.key !== key),
    });
    setVersions(readVersions(answer));
    setLevelDrawer(null);
  } catch (error) {
    setMessage({ ok: false, text: levelInUseText((error as { detail?: unknown })?.detail ?? error) ?? versionErrorText(error) });
  } finally {
    setBusy(false);
  }
}

export async function saveClassificationOverrides(state: ClassificationPolicyState, workspace: ClassifiedWorkspace,
  overrides: Parameters<typeof saveWorkspaceOverrides>[1]) {
  const { setBusy, setOverrideFor, loadWorkspaces, setOverrideProblem } = state;
  setBusy(true);
  try {
    await saveWorkspaceOverrides(workspace.id, overrides);
    setOverrideFor(null);
    await loadWorkspaces();
  } catch (error) {
    const detail = (error as { detail?: { reason?: unknown } }).detail;
    setOverrideProblem(typeof detail?.reason === "string" && detail.reason ? `Not saved: ${detail.reason}.` : versionErrorText(error));
  } finally {
    setBusy(false);
  }
}
