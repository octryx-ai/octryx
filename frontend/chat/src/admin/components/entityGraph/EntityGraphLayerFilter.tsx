// Layer filter of the workspace graph: manual, configuration, operations (deterministic, cited)
// and extracted (Graphiti). The selection is read by the server, so counts describe what was loaded.
import type { GraphLayer } from "./entityGraphTypes";
import { GRAPH_LAYERS, toggleGraphLayer } from "./entityGraphPresentation";

type Props = {
  selected: GraphLayer[];
  onChange: (layers: GraphLayer[]) => void;
  counts?: Partial<Record<GraphLayer, number>>;
};

export function EntityGraphLayerFilter({ selected, onChange, counts }: Props) {
  return <div className="entity-graph__legend" aria-label="Filter by graph layer">
    {GRAPH_LAYERS.map((layer) => {
      const on = selected.includes(layer.id);
      const count = counts?.[layer.id];
      return <button key={layer.id} type="button" aria-pressed={on}
        className={`entity-graph__legend-item${on ? "" : " entity-graph__legend-item--off"}`}
        onClick={() => onChange(toggleGraphLayer(selected, layer.id))}>
        {layer.label}{on && typeof count === "number" ? ` (${count})` : ""}
      </button>;
    })}
  </div>;
}
