import { useCallback, useEffect, useMemo, useState } from "react";
import type { ProjectOption } from "../../../chatOptionTypes";
import { AdminEntityGraphViews } from "../../../admin/components/entityGraph/AdminEntityGraphViews";
import { useAdminNavigation } from "../../../admin/adminNavigation";
import type { AdminTab } from "../../../admin/types/adminPanelTypes.governance";
import { keepWorkspaceInUrl } from "../knowledgeNavigation";
import { KnowledgeRelationshipsPanel } from "../KnowledgeRelationshipsPanel";
import { SegmentedTabs } from "../../../layout/SegmentedTabs";
import { ExploreEntityPanel } from "./ExploreEntityPanel";
import { ExploreFilterBar } from "./ExploreFilterBar";
import {
  EXPLORE_TABS, EXPLORE_VIEW_LABELS, entityPageHref, entityTypeOptions, exploreViews, isEntityPage, keepOfferedType, originOptions,
  readExploreState, relationTypeOptions, searchForHref, withExploreState,
  type ExploreFact, type ExploreFilter, type ExploreState, type ExploreView,
} from "./exploreModel";
import "./knowledge-explore.css";

type Props = {
  workspaceId: string;
  view: ExploreView;
  isAdmin: boolean;
  projects: ProjectOption[];
  onWorkspaceChange: (workspaceId: string) => void;
};

const readState = (): ExploreState =>
  readExploreState(typeof window === "undefined" ? "" : window.location.search);

function writeState(state: ExploreState) {
  if (typeof window === "undefined") return;
  const next = withExploreState(window.location.href, state);
  if (next !== window.location.href) window.history.replaceState(window.history.state, "", next);
}

// Knowledge → Explore: who is connected to what, and what changed. One page with two
// views as segments, List (a compact table of relationships) and Graph (admins), one filter bar and one selected
// entity for both; the entity opens in the side panel over the dimmed list, or as a page. The view is the page id
// (`knowledgeRelationships` or `knowledgeGraph`); filter, entity and "as page" live in the address.
export function KnowledgeExplorePage({ workspaceId, view: requested, isAdmin, projects, onWorkspaceChange }: Props) {
  const { openAdminTab } = useAdminNavigation();
  const views = exploreViews(isAdmin);
  const view: ExploreView = views.includes(requested) ? requested : "list";
  const [state, setState] = useState<ExploreState>(readState);
  const [facts, setFacts] = useState<ExploreFact[]>([]);
  const [nodeTypes, setNodeTypes] = useState<Record<string, number> | undefined>(undefined);
  const [busy, setBusy] = useState(false);
  // "Open as page" for the selected entity: the same address with a flag; closing it goes back to the list.
  const [asPage, setAsPage] = useState(() => isEntityPage(typeof window === "undefined" ? "" : window.location.search));
  useEffect(() => { writeState(state); }, [state]);
  const leavePage = useCallback(() => {
    setAsPage(false);
    if (typeof window !== "undefined") window.history.replaceState(window.history.state, "", entityPageHref(window.location.href, "", false));
  }, []);

  const typeOptions = useMemo(
    () => (view === "graph" ? entityTypeOptions(nodeTypes) : relationTypeOptions(facts)), [view, nodeTypes, facts]);
  const origins = useMemo(() => (view === "list" ? originOptions(facts) : []), [view, facts]);
  const filter: ExploreFilter = { text: state.text, type: keepOfferedType(state.type, typeOptions), origin: state.origin };

  const update = (next: Partial<ExploreState>) => setState((previous) => ({ ...previous, ...next }));
  const selectEntity = useCallback((entity: string) => {
    if (!entity) leavePage();
    setState((previous) => (previous.entity === entity ? previous : { ...previous, entity }));
  }, [leavePage]);
  const open = useCallback((tab: AdminTab) => { keepWorkspaceInUrl(workspaceId); openAdminTab(tab); }, [workspaceId, openAdminTab]);
  const switchTo = (next: ExploreView) => {
    if (next === view) return;
    // The type means something else in the other view (kind of relationship vs. entity type), so it is reset.
    setState((previous) => { const kept = { ...previous, type: "" }; writeState(kept); return kept; });
    open(EXPLORE_TABS[next]);
  };
  // "Show in graph" hands the entity over as the term: the search field shows what the graph looks for, and the
  // graph still centres on the exact entity.
  const showInGraph = () => {
    setState((previous) => { const kept = { ...previous, type: "", text: previous.entity }; writeState(kept); return kept; });
    open(EXPLORE_TABS.graph);
  };
  const searchFor = useCallback((name: string) => {
    if (typeof window !== "undefined") {
      window.history.replaceState(window.history.state, "", searchForHref(window.location.href, name));
    }
    open("knowledgeLibrary");
  }, [open]);

  return (
    <div className="knowledge-explore">
      <div className="knowledge-explore__bar">
        {views.length > 1 ? <SegmentedTabs label="Explore view" idPrefix="explore-view" value={view}
          tabs={views.map((entry) => ({ key: entry, label: EXPLORE_VIEW_LABELS[entry] }))}
          onChange={(next) => switchTo(next as ExploreView)} testId="explore-views" /> : null}
        <ExploreFilterBar filter={filter} typeLabel={view === "graph" ? "Entity type" : "Kind of relationship"}
          typeOptions={typeOptions} originOptions={origins} busy={busy} showType={view !== "graph"}
          onChange={(next) => update({ ...next, entity: next.text !== state.text ? "" : state.entity })} />
      </div>
      {view === "graph" ? (
        <AdminEntityGraphViews projectId={workspaceId} setProjectId={onWorkspaceChange} projects={projects}
          query={filter.text} onlyType={filter.type} selectName={state.entity} onSelectedName={selectEntity}
          onTypes={setNodeTypes} onSearchFor={searchFor} />
      ) : (
        <div className="knowledge-explore__list">
          {/* As a page the list stays mounted but hidden: it loads the relationships the entity shows. */}
          <div hidden={Boolean(state.entity && asPage)}>
            <KnowledgeRelationshipsPanel workspaceId={workspaceId} filter={filter} entity={state.entity}
              onSelectEntity={selectEntity} onFacts={setFacts} onBusy={setBusy} onOpen={open} />
          </div>
          {state.entity ? <ExploreEntityPanel entity={state.entity} facts={facts} canShowGraph={views.includes("graph")}
            mode={asPage ? "page" : "panel"}
            pageHref={typeof window === "undefined" ? undefined : entityPageHref(window.location.href, state.entity)}
            onSearchFor={searchFor} onShowInGraph={showInGraph} onSelectEntity={selectEntity}
            onClose={() => selectEntity("")} /> : null}
        </div>
      )}
    </div>
  );
}
