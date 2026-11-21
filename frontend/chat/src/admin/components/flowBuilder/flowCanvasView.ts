// Flow canvas view limits: when the minimap shows, fit-view padding and the minimum zoom.
// The minimap only helps on graphs larger than the view; on small graphs it covered nodes.
export const MINIMAP_MIN_NODES = 7;
// Fit keeps small graphs at their natural size instead of zooming them up. The palette is a column
// beside the graph, so only the graph's own toolbar overlays its top edge; padding 0.2 keeps nodes
// and ports clear of it and of the graph border (0.12 clipped the first node live judge).
export const FIT_VIEW = { padding: 0.2, maxZoom: 1 };
// React Flow's default minZoom (0.5) stops fitView short on a 390px viewport and cuts off the first node;
// 0.2 lets fit show the whole graph there. Desktop fits stay well above it, so they are unchanged.
export const FLOW_MIN_ZOOM = 0.2;
