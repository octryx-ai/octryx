// The reading context of the graph explorer as a trail: a search, or the neighbourhood around one
// entity. "Show its neighbourhood" pushes the current context; "Back" restores exactly the previous
// one (query, focus and the entity that was open), so nested focus returns predictably.

export type GraphContext = {
  query: string;
  focusNodeId: string;
  focusName: string;
  // The entity whose details were open when the user left this context.
  selectedId: string;
};

export const START_CONTEXT: GraphContext = { query: "", focusNodeId: "", focusName: "", selectedId: "" };

export function pushContext(trail: GraphContext[], current: GraphContext): GraphContext[] {
  return [...trail, current];
}

export function popContext(trail: GraphContext[]): { previous: GraphContext; trail: GraphContext[] } | null {
  if (!trail.length) return null;
  return { previous: trail[trail.length - 1], trail: trail.slice(0, -1) };
}

export function contextLabel(context: GraphContext): string {
  if (context.focusNodeId) return `relationships around ${context.focusName || "the previous entity"}`;
  if (context.query) return `results for “${context.query}”`;
  return "the full view";
}

export function focusHeading(context: GraphContext): string | null {
  return context.focusNodeId ? `Relationships around ${context.focusName || "the selected entity"}` : null;
}

/** A breadcrumb's short name: the whole view, a search, or the entity whose neighbourhood is shown. */
export function crumbLabel(context: GraphContext): string {
  if (context.focusNodeId) return context.focusName || "Selected entity";
  if (context.query) return `“${context.query}”`;
  return "All entities";
}

/** Going back to crumb `index` restores that context and drops everything after it. */
export function cutTrail(trail: GraphContext[], index: number): { previous: GraphContext; trail: GraphContext[] } | null {
  if (index < 0 || index >= trail.length) return null;
  return { previous: trail[index], trail: trail.slice(0, index) };
}
