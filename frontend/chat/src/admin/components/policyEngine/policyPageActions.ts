// Page state types and the actions of Settings → Governance → Policies: tab switches, opening the builder or the
// Cedar editors, removing a policy from the draft, and the row menu and drawer actions built from them.
import type { Dispatch, SetStateAction } from "react";

import type { AdminTab } from "../../types/adminPanelTypes.governance";
import type { BuilderSession } from "./usePolicyBuilder";
import type { CedarSession } from "./PolicyCedarEditor";
import type { MenuEntry } from "./PolicyList";
import { removePolicy } from "./policyEngineApi";
import { refusalText } from "./policyEngineVersions";
import { blankModel, duplicateModel, fromTemplate, readModel } from "./policyBuilderModel";
import type { CatalogTemplate, PolicyItem } from "./policyCatalogModel";
import type { usePoliciesData } from "./usePoliciesData";

export type PoliciesTab = "list" | "templates" | "detectors" | "bench";
export const TABS: { id: PoliciesTab; label: string; route: AdminTab | null }[] = [
  { id: "list", label: "Policies", route: "cedarPolicies" },
  { id: "templates", label: "Templates", route: null },
  { id: "detectors", label: "Detectors", route: null },
  { id: "bench", label: "Test bench", route: "policyTestBench" },
];

export type Drawer = { kind: "policy"; item: PolicyItem; confirmRemove: boolean } | { kind: "engine" } | { kind: "lifecycle" } | null;
export type Mode = { kind: "tabs" } | { kind: "set"; diff: boolean } | { kind: "builder"; session: BuilderSession } | { kind: "cedar"; session: CedarSession };
export type Message = { ok: boolean; text: string };
export type PoliciesData = ReturnType<typeof usePoliciesData>;

export type PolicyPageDeps = {
  data: PoliciesData;
  policies: NonNullable<PoliciesData["policies"]>;
  openAdminTab: (tab: AdminTab) => void;
  setTab: Dispatch<SetStateAction<PoliciesTab>>;
  setMode: Dispatch<SetStateAction<Mode>>;
  setDrawer: Dispatch<SetStateAction<Drawer>>;
  setBusy: Dispatch<SetStateAction<boolean>>;
  setMessage: Dispatch<SetStateAction<Message | null>>;
};

function createNavigation({ data, openAdminTab, setTab, setMode, setDrawer, setBusy, setMessage }: PolicyPageDeps) {
  const run = async (action: () => Promise<unknown>, done: string) => {
    setBusy(true);
    setMessage(null);
    try {
      await action();
      await data.load();
      setMessage({ ok: true, text: done });
    } catch (error) {
      setMessage({ ok: false, text: refusalText(error) });
      await data.load();
    } finally {
      setBusy(false);
    }
  };
  const switchTab = (next: PoliciesTab) => {
    setMode({ kind: "tabs" });
    setTab(next);
    const route = TABS.find((item) => item.id === next)?.route;
    if (route) openAdminTab(route);
  };
  // The decision log lives in Observability → Decisions; this opens it filtered to the policy.
  const showDecisions = (policyId: string) => {
    setDrawer(null);
    if (typeof window !== "undefined") {
      const url = new URL(window.location.href);
      url.searchParams.set("policy", policyId);
      window.history.replaceState(window.history.state, "", url.toString());
    }
    openAdminTab("observabilityDecisions");
  };
  const saved = async (text: string) => {
    await data.load();
    setMode({ kind: "tabs" });
    setTab("list");
    setMessage({ ok: true, text });
  };
  return { run, switchTab, showDecisions, saved };
}

function createEditors({ data, policies, setMode, setDrawer, setMessage }: PolicyPageDeps) {
  const ids = policies.items.map((item) => item.id);
  const openBuilder = (session: BuilderSession) => { setDrawer(null); setMessage(null); setMode({ kind: "builder", session }); };
  const openCedar = async (session: CedarSession) => { await data.ensureSchema(); setDrawer(null); setMessage(null); setMode({ kind: "cedar", session }); };
  const openSet = async (diff: boolean) => { await data.ensureSchema(); setDrawer(null); setMode({ kind: "set", diff }); };
  const newPolicy = () => openBuilder({ model: blankModel(), isNew: true, title: "New policy", originalId: null });
  const startFromTemplate = (template: CatalogTemplate) => openBuilder({ model: fromTemplate(template), isNew: true, title: "New policy from template", originalId: null });
  const edit = (item: PolicyItem) => (item.model
    ? openBuilder({ model: readModel(item.model), isNew: false, title: `Edit · ${item.name}`, originalId: item.id })
    : void openCedar({ text: item.text, originalId: item.id, isNew: false, title: `Edit · ${item.name}` }));
  const duplicate = (item: PolicyItem) => (item.model
    ? openBuilder({ model: duplicateModel(readModel(item.model), ids), isNew: true, title: `Duplicate · ${item.name}`, originalId: null })
    : void openCedar({ text: item.text.replace(`@id("${item.id}")`, `@id("${item.id}-copy")`), originalId: null, isNew: true, title: `Duplicate · ${item.name}` }));
  return { openCedar, openSet, newPolicy, startFromTemplate, edit, duplicate };
}

export function createPolicyPageActions(deps: PolicyPageDeps, busy: boolean) {
  const { policies, setDrawer } = deps;
  const navigation = createNavigation(deps);
  const editors = createEditors(deps);
  const { run, switchTab, showDecisions } = navigation;
  const { edit, duplicate } = editors;
  const target = policies.editTarget;
  const remove = (item: PolicyItem) => {
    if (!target) return;
    setDrawer(null);
    void run(() => removePolicy(target.version, item.id, target.digest), `Removed "${item.name}" from the draft; it takes effect when the draft is published.`);
  };
  const frozen = !target;
  const editable = (item: PolicyItem) => !frozen && item.change !== "removed";

  const menuFor = (item: PolicyItem): MenuEntry[] => [
    { label: item.model ? "Edit" : "Edit Cedar", onSelect: () => edit(item), disabled: !editable(item) },
    { label: "Duplicate", onSelect: () => duplicate(item), disabled: frozen },
    { label: "Test", onSelect: () => switchTab("bench") },
    { label: "Show in Decisions", onSelect: () => showDecisions(item.id) },
    { label: "Remove", onSelect: () => setDrawer({ kind: "policy", item, confirmRemove: true }), disabled: !editable(item) },
  ];
  const drawerActions = (item: PolicyItem, confirmRemove: boolean) => ({
    danger: { label: confirmRemove ? "Confirm remove" : "Remove", disabled: !editable(item) || busy,
      onSelect: () => (confirmRemove ? remove(item) : setDrawer({ kind: "policy", item, confirmRemove: true })) },
    secondary: [
      { label: "Duplicate", onSelect: () => duplicate(item), disabled: frozen },
      { label: "Test", onSelect: () => { setDrawer(null); switchTab("bench"); } },
    ],
    primary: { label: item.model ? "Edit" : "Edit Cedar", onSelect: () => edit(item), disabled: !editable(item) },
  });
  return { ...navigation, ...editors, target, frozen, menuFor, drawerActions };
}

export type PolicyPageActions = ReturnType<typeof createPolicyPageActions>;
