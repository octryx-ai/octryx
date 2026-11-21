// Knowledge lookup limits of a Workspace: the defaults, the fields with their ranges and the normalization of a
// stored config.
export type KnowledgeLookupDefaults = {
  knowledge_search_initial_limit?: number;
  overview_knowledge_search_limit?: number;
  overview_graph_depth?: number;
  overview_graph_max_nodes?: number;
  overview_key_catalog_limit?: number;
};

type ProjectConfigPayload = {
  knowledge_lookup?: KnowledgeLookupDefaults;
};

export type KnowledgeLookupConfig = {
  config: ProjectConfigPayload;
};

export type SavedKnowledgeLookupDefaults = Required<KnowledgeLookupDefaults>;

export const DEFAULT_KNOWLEDGE_LOOKUP_DEFAULTS: SavedKnowledgeLookupDefaults = {
  knowledge_search_initial_limit: 30,
  overview_knowledge_search_limit: 40,
  overview_graph_depth: 4,
  overview_graph_max_nodes: 120,
  overview_key_catalog_limit: 200,
};

// One line per limit on what it changes. Values are applied when a knowledge
// lookup workflow runs in this workspace; a workflow's own settings win.
export const LOOKUP_FIELDS: Array<{
  key: keyof SavedKnowledgeLookupDefaults;
  label: string;
  help: string;
  min: number;
  max: number;
}> = [
  {
    key: "knowledge_search_initial_limit",
    label: "Initial knowledge search limit",
    help: "Passages the first search returns. Higher finds more but fills more of the model context.",
    min: 1,
    max: 200,
  },
  {
    key: "overview_knowledge_search_limit",
    label: "Overview knowledge search limit",
    help: "Passages an overview question pulls in before it summarizes.",
    min: 1,
    max: 200,
  },
  {
    key: "overview_graph_depth",
    label: "Graph depth",
    help: "Relationship hops an overview follows from each match. Deeper shows wider context and is slower.",
    min: 1,
    max: 10,
  },
  {
    key: "overview_graph_max_nodes",
    label: "Graph max nodes",
    help: "Upper bound on entities an overview graph may include.",
    min: 10,
    max: 5000,
  },
  {
    key: "overview_key_catalog_limit",
    label: "Overview key catalog limit",
    help: "Key entries an overview may list at most.",
    min: 20,
    max: 1000,
  },
];

function toNumber(value: string, fallback: number): number {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : fallback;
}

export function clampNumber(value: number, min: number, max: number, fallback: number): number {
  const normalized = Number.isFinite(value) ? value : fallback;
  if (normalized < min) return min;
  if (normalized > max) return max;
  return Math.trunc(normalized);
}

export function normalizeKnowledgeLookupConfig(
  raw: KnowledgeLookupDefaults | undefined,
): SavedKnowledgeLookupDefaults {
  const values = raw || {};
  return {
    knowledge_search_initial_limit: clampNumber(
      toNumber(String(values.knowledge_search_initial_limit), DEFAULT_KNOWLEDGE_LOOKUP_DEFAULTS.knowledge_search_initial_limit),
      1,
      200,
      DEFAULT_KNOWLEDGE_LOOKUP_DEFAULTS.knowledge_search_initial_limit,
    ),
    overview_knowledge_search_limit: clampNumber(
      toNumber(
        String(values.overview_knowledge_search_limit),
        DEFAULT_KNOWLEDGE_LOOKUP_DEFAULTS.overview_knowledge_search_limit,
      ),
      1,
      200,
      DEFAULT_KNOWLEDGE_LOOKUP_DEFAULTS.overview_knowledge_search_limit,
    ),
    overview_graph_depth: clampNumber(
      toNumber(String(values.overview_graph_depth), DEFAULT_KNOWLEDGE_LOOKUP_DEFAULTS.overview_graph_depth),
      1,
      10,
      DEFAULT_KNOWLEDGE_LOOKUP_DEFAULTS.overview_graph_depth,
    ),
    overview_graph_max_nodes: clampNumber(
      toNumber(String(values.overview_graph_max_nodes), DEFAULT_KNOWLEDGE_LOOKUP_DEFAULTS.overview_graph_max_nodes),
      10,
      5000,
      DEFAULT_KNOWLEDGE_LOOKUP_DEFAULTS.overview_graph_max_nodes,
    ),
    overview_key_catalog_limit: clampNumber(
      toNumber(
        String(values.overview_key_catalog_limit),
        DEFAULT_KNOWLEDGE_LOOKUP_DEFAULTS.overview_key_catalog_limit,
      ),
      20,
      1000,
      DEFAULT_KNOWLEDGE_LOOKUP_DEFAULTS.overview_key_catalog_limit,
    ),
  };
}
