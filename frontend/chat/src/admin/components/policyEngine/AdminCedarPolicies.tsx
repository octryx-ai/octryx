import { lazy, useEffect, useMemo, useState } from "react";
import type { ComponentType } from "react";

import { useAdminNavigation } from "../../adminNavigation";
import { useApprovalRule } from "../approvalRule/approvalRule";
import { PolicyBuilderPanel, PolicyDrawers, PolicyTabsView } from "./AdminCedarPoliciesParts";
import type { PolicyPageCtx } from "./AdminCedarPoliciesParts";
import type { CedarEditorProps } from "./CedarPolicyEditor";
import { CedarSetEditor } from "./CedarSetEditor";
import { PolicyCedarEditor } from "./PolicyCedarEditor";
import { PolicyNamesContext } from "./policyNames";
import { NO_FILTERS, actionOf, readUrlFilters } from "./policyCatalogModel";
import { clearPolicyFilter } from "./policyLinks";
import type { ListFilters } from "./policyCatalogModel";
import { createPolicyPageActions } from "./policyPageActions";
import type { Drawer, Message, Mode, PoliciesTab } from "./policyPageActions";
import { usePoliciesData } from "./usePoliciesData";
import "../adminChannels.css";
import "./policiesPage.css";
import "./policyBuilder.css";
import "./policyDrawers.css";

const MonacoCedarEditor = lazy(() => import("./CedarPolicyEditor"));

// Settings → Governance → Policies (WP): the engine status in the header, the tabs
// Policies / Templates / Detectors / Test bench (the decision log is Observability → Decisions), the draft bar, the policy
// table with its drawer, the guided builder, the per-policy Cedar editor, and the whole set as Cedar behind
// "Advanced". Cedar stays the stored truth; the lifecycle (four-eyes publish, test cases, rollback) is unchanged.
export function AdminCedarPolicies({ editor = MonacoCedarEditor, view: routeView = "list", search = typeof window !== "undefined" ? window.location.search : "", previewDelay }: {
  editor?: ComponentType<CedarEditorProps>;
  view?: PoliciesTab;
  search?: string;
  previewDelay?: number;
}) {
  const { openAdminTab } = useAdminNavigation();
  const [tab, setTab] = useState<PoliciesTab>(routeView);
  const [mode, setMode] = useState<Mode>({ kind: "tabs" });
  const [filters, setFilters] = useState<ListFilters>(() => ({ ...NO_FILTERS, ...readUrlFilters(search) }));
  const [drawer, setDrawer] = useState<Drawer>(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<Message | null>(null);
  const data = usePoliciesData(filters.showGenerated);
  const approvalRule = useApprovalRule();
  const { status, policies, catalog, entities, working, published } = data;
  const names = useMemo(() => ({
    workspaces: Object.fromEntries(entities.workspaces.map((item) => [item.id, item.name])),
    policies: Object.fromEntries([...(policies?.generated ?? []), ...(policies?.items ?? [])].map((item) => [item.id, item.name])),
  }), [entities.workspaces, policies]);

  useEffect(() => { setTab(routeView); }, [routeView]);
  // A deep-link filter (policyLinks) applies once; the next visit starts unfiltered.
  useEffect(() => { clearPolicyFilter(); }, []);

  if (data.problem) return <p className="workspace-classification__message" role="alert" data-testid="cedar-policies-error">{data.problem}</p>;
  if (!status || !policies) return <p className="admin-panel__hint" role="status">Loading the policies…</p>;

  const actions = createPolicyPageActions({ data, policies, openAdminTab, setTab, setMode, setDrawer, setBusy, setMessage }, busy);
  const ctx: PolicyPageCtx = {
    data, policies, status, actions, approvalRule, previewDelay, openAdminTab, setDrawer, setMode, setMessage,
    labelOf: (action: string) => actionOf(catalog, action)?.label ?? action,
  };

  return (
    <PolicyNamesContext.Provider value={names}>
    <div className="policies" data-testid="policies-page">
      {mode.kind === "set" ? (
        <CedarSetEditor editor={editor} schema={data.schema} published={published} working={working}
          initialDiff={mode.diff} onBack={() => setMode({ kind: "tabs" })} onChanged={data.load} />
      ) : mode.kind === "cedar" ? (
        <PolicyCedarEditor editor={editor} schema={data.schema} session={mode.session} view={policies}
          onCancel={() => setMode({ kind: "tabs" })} onSaved={actions.saved} />
      ) : (
        <PolicyTabsView ctx={ctx} tab={tab} filters={filters} setFilters={setFilters} message={message} />
      )}
      {/* New policy / Edit: the builder opens as a side panel over the dimmed list. */}
      {mode.kind === "builder" && catalog ? <PolicyBuilderPanel ctx={ctx} session={mode.session} /> : null}
      <PolicyDrawers ctx={ctx} drawer={drawer} />
    </div>
    </PolicyNamesContext.Provider>
  );
}
