// Current workspace GraphDB explorer: source-authorized relationships as a graph a person can read. A top bar
// with the "N of M" count, the focus trail and Advanced; the clustered canvas (kgLayout) with the legend as the
// type filter; the selected entity's details docked beside it; the ranked entity list as the accessible path;
// and inspectable evidence for every link.

import { useEffect } from "react";
import { countLine, onlyType as soloType, toggleType } from "./kgView";
import { groupsNote } from "./kgCommunities";
import { EntityGraphKindFilter } from "./EntityGraphKindFilter";
import { graphDestination, graphNotice, typeLegend } from "./entityGraphPresentation";
import { EntityGraphLayerFilter } from "./EntityGraphLayerFilter";
import { EntityGraphCanvas } from "./EntityGraphCanvas";
import { EntityGraphFocusBar } from "./EntityGraphFocusBar";
import { EntityGraphLegend } from "./EntityGraphLegend";
import { EntityGraphRelationships } from "./EntityGraphRelationships";
import { EntityGraphToolbar } from "./EntityGraphToolbar";
import { nodeNamed, ONLY_NOISE_NOTE } from "./entityGraphNoise";
import { useEntityGraphLayout, useEntityGraphLegend, useEntityGraphVisibility } from "./useEntityGraphView";
import { useEntityGraphExpand } from "./useEntityGraphExpand";
import {
  useEntityGraphDetail, useEntityGraphFocus, useEntityGraphLoad, useEntityGraphState, type EntityGraphState,
} from "./useEntityGraphPanelState";
import "./entity-graph-matches.css";
import "./knowledge-graph.css";

type Props = {
  projectId: string;
  // Knowledge → Explore drives the graph from its shared filter bar: the term (then the graph's own
  // search field is hidden), one entity type, the entity selected in the other view, and "Search for this".
  query?: string;
  onlyType?: string;
  selectName?: string;
  onSelectedName?: (name: string) => void;
  onTypes?: (nodeTypes: Record<string, number> | undefined) => void;
  onSearchFor?: (name: string) => void;
};

// A loaded graph centres on the entity "Show in graph" named, reopens the entity selected before, and reports its types.
function useEntityGraphReopen(g: EntityGraphState, selectName: string, openDetail: (nodeId: string) => Promise<void>,
  onTypes?: (nodeTypes: Record<string, number> | undefined) => void) {
  const { payload, centring, reopenId, setActiveQuery, setQuery, setFocusName, setFocusNodeId } = g;
  useEffect(() => {
    const name = centring.current;
    if (!payload || !name) return;
    centring.current = "";
    const centre = nodeNamed(payload.nodes, name);
    if (!centre) return;
    setActiveQuery(""); setQuery(""); setFocusName(centre.display_name); setFocusNodeId(centre.id);
    reopenId.current = centre.id;
  }, [payload, centring, reopenId, setActiveQuery, setQuery, setFocusName, setFocusNodeId]);

  useEffect(() => {
    if (!payload || centring.current) return;
    // The entity selected before (Back, or the other Explore view) opens again when this view shows it.
    const named = selectName.trim().toLowerCase();
    const wanted = reopenId.current
      || (named ? payload.nodes.find((node) => node.display_name.trim().toLowerCase() === named)?.id ?? "" : "");
    reopenId.current = "";
    if (wanted && payload.nodes.some((node) => node.id === wanted)) void openDetail(wanted);
    // Only a new payload reopens; a selection made here is already open.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [payload, openDetail]);

  useEffect(() => { onTypes?.(payload?.state === "ok" ? payload.stats?.node_types : undefined); }, [payload, onTypes]);
}

// What the view shows: layout, visible entities and links, Expand, the legend, the notice and the count line.
function useEntityGraphViewModel(g: EntityGraphState, projectId: string, onlyType: string, nameOf: (nodeId: string) => string) {
  const { payload, additions, showNoise, focusNodeId, hiddenTypes, hiddenKinds, selectedId, layers, requestEpoch, noteTimer,
    setExpandNote, setAdditions, setFreshIds, setError, activeQuery, loading } = g;
  const layout = useEntityGraphLayout({ payload, additions, showNoise, focusNodeId, onlyType, hiddenTypes });
  const { grouping, positions, loadedNodes, loadedEdges } = layout;
  const visibility = useEntityGraphVisibility({
    payload, additions, grouping, loadedNodes, loadedEdges, hiddenTypes, hiddenKinds, selectedId });
  const { slots, visibleNodes, visibleIds, visibleEdges } = visibility;

  // Expand adds what is new around an entity to this view; it never replaces the view. The ids the view
  // shows go along (over the server's limit: the selection, the entity, its neighbours and the hubs first).
  const expandNode = useEntityGraphExpand({ projectId, payload, additions, positions, selectedId, layers, nameOf,
    requestEpoch, noteTimer, setExpandNote, setAdditions, setFreshIds, setError });

  // Groups: the catch-all groups go last in the legend, whatever their size.
  // The loosely connected ring: fitted around, not into; its lines drawn faint.
  const legendView = useEntityGraphLegend({ payload, grouping, loadedNodes, visibleNodes,
    visibleIds, hiddenTypes, slots, activeQuery });
  const { legend, bases } = legendView;
  const allTypes = legend.map((item) => item.type);
  const typeInfo = typeLegend(payload?.stats?.node_types);
  const onlyKind = Object.keys(payload?.stats?.node_types ?? {})[0];
  const typeNote = grouping ? groupsNote(onlyKind) : typeInfo?.kind === "note" ? typeInfo.text : undefined;
  const notice = graphNotice(payload, visibleNodes.length, activeQuery, focusNodeId);
  const reading = Boolean(payload && !notice && !loading);
  const count = payload?.state === "ok" && loadedNodes.length
    ? countLine({ shown: visibleNodes.length, loaded: loadedNodes.length, relationships: visibleEdges.length,
      totalNodes: payload.stats?.total_nodes, totalEdges: payload.stats?.total_edges })
      + (activeQuery.trim() ? ` · ${bases.size} ${bases.size === 1 ? "match" : "matches"} for “${activeQuery.trim()}”` : "")
    : null;
  return { ...layout, ...visibility, ...legendView, expandNode, allTypes, typeNote, notice, reading, count };
}

type EntityGraphViewModel = ReturnType<typeof useEntityGraphViewModel>;

// The load error, the loading state and the notice in place of the graph (empty, not configured, no matches).
function EntityGraphStatus({ error, loading, notice, payloadState, projectId, onRetry, onReset }: {
  error: string;
  loading: boolean;
  notice: EntityGraphViewModel["notice"];
  payloadState: string;
  projectId: string;
  onRetry: () => void;
  onReset: () => void;
}) {
  return (
    <>
      {error ? <div className="admin-panel__error" role="alert">{error}
        <button type="button" className="admin-panel__action-btn" onClick={onRetry}>Retry graph</button>
      </div> : null}
      {loading ? <div className="kg-state kg-state--loading" role="status" aria-busy="true">
        <span className="kg-state__pulse" aria-hidden="true" />
        <p className="kg-state__title">Loading the graph…</p>
      </div> : null}
      {notice && !loading ? <section className="kg-state" role="status">
        <h3 className="kg-state__title">{notice.title}</h3><p className="kg-state__text">{notice.text}</p>
        <div className="kg-state__actions">
          {notice.reset ? <button type="button" className="admin-panel__action-btn" onClick={onReset}>Reset search and filters</button> : <>
            <a className="admin-panel__action-btn" href={graphDestination(projectId, "documents")}>Open Documents</a>
            <a className="admin-panel__action-btn" href={graphDestination(projectId, "repositories")}>Repository explorer</a>
          </>}
          {!["ok", "not_extracted", "no_matches"].includes(payloadState) &&
            <button type="button" className="admin-panel__action-btn" onClick={onRetry}>Retry graph</button>}
        </div>
      </section> : null}
    </>
  );
}

// The clustered canvas with its legend and the selected entity's details.
function EntityGraphReader({ g, view, projectId, openDetail, focusOn, closeDetail, onSearchFor }: {
  g: EntityGraphState;
  view: EntityGraphViewModel;
  projectId: string;
  openDetail: (nodeId: string) => Promise<void>;
  focusOn: (nodeId: string) => void;
  closeDetail: () => void;
  onSearchFor?: (name: string) => void;
}) {
  const { selectedId, activeQuery, detail, detailLoading, listOpen, freshIds, setHiddenTypes } = g;
  const { visibleNodes, visibleEdges, positions, slots, neighborIds, matches, bases, viewKey, clusterLabels, grouping, fitIds,
    ringIds, expandNode, legend, allTypes, typeNote } = view;
  return (
    <EntityGraphCanvas workspaceId={projectId} nodes={visibleNodes} edges={visibleEdges}
      positions={positions} slots={slots} selectedId={selectedId} neighborIds={neighborIds} matches={matches} bases={bases}
      query={activeQuery} searching={Boolean(activeQuery)} detail={selectedId ? detail : null} detailLoading={detailLoading}
      listOpen={listOpen} freshIds={freshIds} viewKey={viewKey} clusters={clusterLabels} labelPool={grouping?.hubs}
      fitIds={fitIds}
      faintIds={ringIds.size ? ringIds : undefined} onExpand={(id) => void expandNode(id)}
      legend={<EntityGraphLegend items={legend} onToggle={(type) => setHiddenTypes((previous) => toggleType(previous, type))}
        onOnly={(type) => setHiddenTypes((previous) => soloType(previous, type, allTypes))}
        onShowAll={() => setHiddenTypes(new Set())} note={typeNote} kind={grouping ? "groups" : "types"} />}
      onSelect={(id) => void openDetail(id)} onFocus={focusOn} onClose={closeDetail} onSearchFor={onSearchFor} />
  );
}

export function AdminEntityGraphPanel({ projectId, query: sharedQuery, onlyType = "", selectName = "", onSelectedName,
  onTypes, onSearchFor }: Props) {
  const g = useEntityGraphState(sharedQuery, selectName);
  const { payload, loading, error, query, setQuery, activeQuery, setActiveQuery, focusNodeId, setFocusNodeId, focusName,
    setFocusName, trail, setTrail, setHiddenTypes, hiddenKinds, setHiddenKinds, maxNodes, setMaxNodes, listOpen, setListOpen,
    showNoise, setShowNoise, layers, setLayers, selectedId, expandNote } = g;
  const loadGraph = useEntityGraphLoad(g, projectId, sharedQuery);
  const { openDetail, closeDetail } = useEntityGraphDetail(g, projectId, onSelectedName);
  const { nameOf, focusOn, goBack } = useEntityGraphFocus(g);
  useEntityGraphReopen(g, selectName, openDetail, onTypes);
  const view = useEntityGraphViewModel(g, projectId, onlyType, nameOf);
  const { noiseOnly, kinds, visibleNodes, visibleEdges, notice, reading, count } = view;
  const clearContext = () => { setQuery(""); setActiveQuery(""); setFocusNodeId(""); setFocusName(""); setTrail([]); };
  // Back to the defaults: no search or focus, every type and relationship kind shown, structure nodes by the default.
  const reset = () => { clearContext(); setHiddenTypes(new Set()); setHiddenKinds(new Set()); setShowNoise(false); };
  const current = { query: activeQuery, focusNodeId, focusName, selectedId };
  return (
    <div className="entity-graph kg">
      <EntityGraphToolbar query={query} onQueryChange={setQuery}
        onSearch={() => { setFocusNodeId(""); setFocusName(""); setTrail([]); setActiveQuery(query.trim()); }}
        canReset={Boolean(activeQuery || focusNodeId)} onReset={clearContext}
        maxNodes={maxNodes} onMaxNodes={setMaxNodes} showNoise={showNoise} onShowNoise={setShowNoise}
        count={count} note={expandNote || (noiseOnly ? ONLY_NOISE_NOTE : "")}
        truncated={Boolean(payload?.truncated) && typeof payload?.stats?.total_nodes !== "number"} listOpen={listOpen} onListOpen={reading ? setListOpen : undefined}
        kinds={kinds.length > 1 ? <EntityGraphKindFilter kinds={kinds} hidden={hiddenKinds}
          onToggle={(kind) => setHiddenKinds((previous) => toggleType(previous, kind))} /> : undefined}
        layers={<EntityGraphLayerFilter selected={layers} onChange={setLayers} counts={payload?.stats?.layers} />}
        trail={<EntityGraphFocusBar current={current} trail={trail} onBack={goBack} />}
        showSearch={sharedQuery === undefined} />
      <EntityGraphStatus error={error} loading={loading} notice={notice} payloadState={payload?.state || ""} projectId={projectId}
        onRetry={() => void loadGraph()} onReset={reset} />
      {reading ? <EntityGraphReader g={g} view={view} projectId={projectId} openDetail={openDetail} focusOn={focusOn}
        closeDetail={closeDetail} onSearchFor={onSearchFor} /> : null}
      {reading && payload?.state === "ok" ? <EntityGraphRelationships
        payload={{ ...payload, nodes: visibleNodes, edges: visibleEdges }} onSelect={(id) => void openDetail(id)} /> : null}
    </div>
  );
}
