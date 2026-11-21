import { useEffect, useState } from "react";

import type { AdminTab } from "../../../admin/types/adminPanelTypes.governance";
import { readJson } from "../../../admin/utils/adminPanelHelpers";
import { codingPayload, readCoding, settingsErrorText, type Coding, type ToolRule } from "../../../admin/components/workspaceSettings/workspaceSettingsModel";
import { loadEffectiveRules, type EffectiveRules } from "./codingRulesApi";
import type { CodingRuleRow, RuleEditPlace } from "./codingRulesTable";

type Setter<T> = (value: T | ((previous: T) => T)) => void;

export type CodingRulesProps = {
  workspaceId: string;
  onOpenAdminTab: (tab: AdminTab) => void;
  onOpenPipeline: () => void;
  onOpenWorkspaceCoding?: () => void;
  onAddingChange?: (adding: boolean) => void;
  onEditableChange?: (editable: boolean) => void;
};

type CodingRulesState = {
  coding: Coding | null; codingPath: string;
  setNotice: Setter<string | null>; setReload: Setter<number>;
  setOpenKey: Setter<string | null>; setRemoving: Setter<CodingRuleRow | null>; setSaving: Setter<boolean>;
  setPanelError: Setter<string | null>;
};

// The page's state and its two reads: the effective rules, and the Workspace's own rules (readable only by those who
// may change them; anyone else sees no "Add rule").
export function useCodingEffectiveRules(props: CodingRulesProps) {
  const { workspaceId, onEditableChange } = props;
  const [rules, setRules] = useState<EffectiveRules | null>(null);
  const [coding, setCoding] = useState<Coding | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [reload, setReload] = useState(0);
  const [openKey, setOpenKey] = useState<string | null>(null);
  const [removing, setRemoving] = useState<CodingRuleRow | null>(null);
  const [saving, setSaving] = useState(false);
  const [panelError, setPanelError] = useState<string | null>(null);
  const codingPath = `/api/v1/admin/workspaces/${encodeURIComponent(workspaceId)}/coding`;

  useEffect(() => {
    let active = true;
    setError(null);
    loadEffectiveRules(workspaceId).then((next) => active && setRules(next))
      .catch((failure) => active && setError(failure instanceof Error ? failure.message : "Could not load the rules."));
    return () => { active = false; };
  }, [workspaceId, reload]);

  useEffect(() => {
    let active = true;
    setCoding(null);
    onEditableChange?.(false);
    readJson<unknown>(codingPath).then((answer) => {
      if (!active) return;
      const read = readCoding(answer);
      setCoding(read);
      onEditableChange?.(read !== null);
    }).catch(() => undefined);
    return () => { active = false; };
    // The callback is the page's state setter; only the Workspace changes what is read.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [codingPath, reload]);

  const state: CodingRulesState = { coding, codingPath, setNotice, setReload, setOpenKey, setRemoving, setSaving, setPanelError };
  return { rules, coding, error, notice, openKey, removing, saving, panelError, setOpenKey, setRemoving, setPanelError,
    ...codingRuleActions(state, props) };
}

function codingRuleActions(state: CodingRulesState, props: CodingRulesProps) {
  const { coding, codingPath, setNotice, setReload, setOpenKey, setRemoving, setSaving, setPanelError } = state;
  // The Workspace rule behind a row, when this person may change it (their coding settings were readable).
  const workspaceRule = (row: CodingRuleRow | null): ToolRule | null => {
    if (!row || !coding) return null;
    return coding.toolRules.find((rule) => row.ruleIds?.includes(rule.id)) ?? null;
  };

  async function saveRules(toolRules: ToolRule[], done: string) {
    if (!coding) return false;
    setSaving(true);
    setPanelError(null);
    try {
      await readJson<unknown>(codingPath, { method: "PUT", body: JSON.stringify(codingPayload({ ...coding, toolRules })) });
      setNotice(done);
      setReload((value) => value + 1);
      return true;
    } catch (failure) {
      setPanelError(settingsErrorText(failure));
      return false;
    } finally {
      setSaving(false);
    }
  }
  return { workspaceRule, ...ruleChanges(coding, props, { saveRules, workspaceRule, setOpenKey, setRemoving, setPanelError }) };
}

type RuleChangeTools = {
  saveRules: (toolRules: ToolRule[], done: string) => Promise<boolean>;
  workspaceRule: (row: CodingRuleRow | null) => ToolRule | null;
  setOpenKey: Setter<string | null>; setRemoving: Setter<CodingRuleRow | null>; setPanelError: Setter<string | null>;
};

function ruleChanges(coding: Coding | null, props: CodingRulesProps, tools: RuleChangeTools) {
  const { saveRules, workspaceRule, setOpenKey, setRemoving, setPanelError } = tools;
  const { onAddingChange, onOpenPipeline, onOpenWorkspaceCoding, onOpenAdminTab } = props;
  async function addRule(rule: ToolRule) {
    if (!coding) return;
    if (await saveRules([...coding.toolRules, rule], "Rule added. It applies to the next tool call.")) onAddingChange?.(false);
  }

  async function changeRule(previous: ToolRule, rule: ToolRule) {
    if (!coding) return;
    const next = coding.toolRules.map((entry) => (entry.id === previous.id ? rule : entry));
    if (await saveRules(next, "Rule saved. It applies to the next tool call.")) setOpenKey(null);
  }

  async function removeRule(row: CodingRuleRow) {
    const rule = workspaceRule(row);
    if (!coding || !rule) return;
    if (await saveRules(coding.toolRules.filter((entry) => entry.id !== rule.id), "Rule removed.")) {
      setRemoving(null);
      setOpenKey(null);
    }
  }

  const closePanel = () => {
    setPanelError(null);
    setOpenKey(null);
    onAddingChange?.(false);
  };

  const openEdit = (place: RuleEditPlace) => {
    if (place === "pipeline") onOpenPipeline();
    else if (place === "workspaceCoding") (onOpenWorkspaceCoding ?? (() => onOpenAdminTab("projects")))();
    else onOpenAdminTab(place);
  };
  return { addRule, changeRule, removeRule, closePanel, openEdit };
}
