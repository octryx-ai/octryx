// The graph's stage. Desktop: the canvas fills the stage, the legend sits on it, the selected entity's details
// dock on the right (the graph stays visible and dims everything outside the neighbourhood), and the ranked
// entity list opens on the left as the accessible reading path. Phone (narrow stage): the ranked list first; a
// selection shows that entity's focused neighbourhood above its details. Escape closes the details and returns
// focus to the list item.

import { lazy, Suspense, useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import type { EntityGraphEdge, EntityGraphNode, EntityNodeDetail } from "./entityGraphTypes";
import type { MatchBasis } from "./entityGraphMatches";
import type { ClusterBox, Placed } from "./kgLayout";
import { egoLayout } from "./kgLayout";
import { slotColor } from "./kgView";
import { rankEntities } from "./entityGraphReading";
import { AdminEntityGraphDetailPanel } from "./AdminEntityGraphDetailPanel";
import { EntityGraphEntityList } from "./EntityGraphEntityList";
import "./entity-graph-reader.css";

// The canvas chunk is small (React Flow itself is in the shared vendor chunk), but fetched only on first draw it
// waited behind the graph answer and any busy connection: on Preview "Drawing the graph…" stood for ~6 s. The
// panel now starts the fetch when it mounts (preloadGraphCanvas), in parallel with the graph request.
const loadCanvas = () => import("./KnowledgeGraphCanvas");
let canvasModule: ReturnType<typeof loadCanvas> | null = null;
/** Starts fetching the canvas code (once); the lazy component below then finds it ready. */
export function preloadGraphCanvas() {
  canvasModule ??= loadCanvas();
  return canvasModule;
}
const KnowledgeGraphCanvas = lazy(preloadGraphCanvas);

// Below this stage width the phone reading applies (list first, focused neighbourhood on selection).
export const NARROW_STAGE_PX = 640;

type Props = {
  workspaceId: string;
  nodes: EntityGraphNode[]; edges: EntityGraphEdge[]; positions: Map<string, Placed>; slots: Map<string, number>;
  selectedId: string; neighborIds: Set<string>; matches: Set<string>; bases: Map<string, MatchBasis>;
  query: string; searching: boolean;
  detail: EntityNodeDetail | null; detailLoading: boolean;
  listOpen?: boolean;
  // Entities an Expand just added (highlighted for a moment); Expand itself adds to the view.
  freshIds?: Set<string>;
  viewKey?: string;
  clusters?: ClusterBox[];
  labelPool?: Set<string>;
  fitIds?: string[];
  faintIds?: Set<string>;
  onExpand?: (id: string) => void;
  legend?: ReactNode;
  onSelect: (id: string) => void; onFocus: (id: string) => void; onClose: () => void;
  onSearchFor?: (name: string) => void;
};

/** The stage's width once measured (0 before, and where nothing can be measured). */
function useWidth(ref: React.RefObject<HTMLElement | null>): number {
  const [width, setWidth] = useState(0);
  useEffect(() => {
    const element = ref.current;
    if (!element || typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(() => setWidth(element.clientWidth));
    observer.observe(element);
    return () => observer.disconnect();
  }, [ref]);
  return width;
}

export function EntityGraphCanvas(props: Props) {
  const { nodes, edges, positions, slots, selectedId, neighborIds, matches, onSelect, onFocus, onClose } = props;
  const ranked = useMemo(() => rankEntities(nodes, edges, matches), [nodes, edges, matches]);
  const viewIds = useMemo(() => new Set(nodes.map((node) => node.id)), [nodes]);
  const stage = useRef<HTMLDivElement | null>(null);
  const returnFocus = useRef("");
  const width = useWidth(stage);
  const narrow = width > 0 && width < NARROW_STAGE_PX;

  const close = useCallback(() => {
    returnFocus.current = selectedId;
    onClose();
  }, [selectedId, onClose]);

  useEffect(() => {
    const id = returnFocus.current;
    if (selectedId || !id) return;
    returnFocus.current = "";
    const items = stage.current?.querySelectorAll<HTMLElement>("[data-entity-id]") ?? [];
    for (const item of items) {
      if (item.dataset.entityId === id && item.offsetParent) { item.focus({ preventScroll: true }); break; }
    }
  }, [selectedId]);

  // The phone's picture: the selected entity and its neighbours only.
  const ego = useMemo(() => {
    if (!narrow || !selectedId) return null;
    const centre = nodes.find((node) => node.id === selectedId);
    if (!centre) return null;
    const around = nodes.filter((node) => node.id !== selectedId && neighborIds.has(node.id));
    const ids = new Set([selectedId, ...around.map((node) => node.id)]);
    return {
      nodes: [centre, ...around], positions: egoLayout(centre, around),
      edges: edges.filter((edge) => ids.has(edge.source) && ids.has(edge.target) && (edge.source === selectedId || edge.target === selectedId)),
    };
  }, [narrow, selectedId, nodes, edges, neighborIds]);

  const canvas = (mode: "full" | "ego") => <Suspense fallback={<p className="kg-stage__wait" role="status">Drawing the graph…</p>}>
    <KnowledgeGraphCanvas mode={mode} nodes={mode === "ego" && ego ? ego.nodes : nodes}
      edges={mode === "ego" && ego ? ego.edges : edges} positions={mode === "ego" && ego ? ego.positions : positions}
      slots={slots} selectedId={selectedId} matches={matches} fresh={props.freshIds} viewKey={mode === "full" ? props.viewKey : undefined}
      clusters={mode === "full" ? props.clusters : undefined} labelPool={mode === "full" ? props.labelPool : undefined}
      fitIds={mode === "full" ? props.fitIds : undefined} faintIds={mode === "full" ? props.faintIds : undefined} onSelect={onSelect}
      onExpand={props.onExpand ?? onFocus} onClear={close} />
  </Suspense>;
  const listShown = narrow ? !selectedId : Boolean(props.listOpen);
  const typeOf = props.detail?.node_type ?? nodes.find((node) => node.id === selectedId)?.node_type ?? "";

  return <div ref={stage} className="kg-stage" data-narrow={narrow || undefined} data-list={listShown || undefined}
    data-detail={selectedId ? true : undefined}
    onKeyDown={(event) => { if (event.key === "Escape" && selectedId) { event.preventDefault(); close(); } }}>
    {narrow && !selectedId ? props.legend : null}
    <aside className="kg-stage__list" hidden={!listShown}>
      <EntityGraphEntityList ranked={ranked} bases={props.bases} query={props.query} selectedId={selectedId}
        neighborIds={neighborIds} searching={props.searching} onSelect={onSelect} />
    </aside>
    {narrow
      ? (ego ? <div className="kg-stage__ego">{canvas("ego")}</div> : null)
      : <div className="kg-stage__canvas">
        {width > 0 ? canvas("full") : null}
        {props.legend}
      </div>}
    {selectedId ? <AdminEntityGraphDetailPanel workspaceId={props.workspaceId} entityId={selectedId}
      entityName={nodes.find((node) => node.id === selectedId)?.display_name ?? ""} detail={props.detail} loading={props.detailLoading}
      typeColor={slotColor(slots.get(typeOf))}
      viewEdges={edges} viewIds={viewIds} onSelect={onSelect} onFocusNode={onFocus} onExpand={props.onExpand} onBack={close}
      onSearchFor={props.onSearchFor} /> : null}
  </div>;
}
