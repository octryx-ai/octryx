// Which graph nodes are structure or literal values rather than things a person explores.
// Structure nodes (documents, chapters, sections, config files) organize the sources; literal values ("false", ";",
// "DEFAULT", "42") are setting values the extraction picked up as entities. Both are hidden by default and can be
// shown under Advanced. The rule is on the node itself only, never on its neighbours, and the entity a view is
// centred on is always kept.

export const STRUCTURE_NODE_TYPES: ReadonlySet<string> = new Set(["Document", "Chapter", "Section", "ConfigFile"]);

// Literal words that are values, not entities: booleans, empty values and placeholder keywords.
const LITERAL_WORDS: ReadonlySet<string> = new Set([
  "true", "false", "yes", "no", "on", "off", "null", "none", "nil", "undefined", "n/a", "na", "default", "empty",
]);

export type GraphNoise = "structure" | "literal" | null;

/** Whether a name is a literal value: punctuation only, a single character, a number or a literal word. */
export function isLiteralName(name: string): boolean {
  const text = name.trim();
  if (!text) return true;
  if (text.length === 1) return true;
  if (/^[\p{P}\p{S}\s]+$/u.test(text)) return true;
  if (/^[-+]?\d+(?:[.,]\d+)*\s*(?:%|ms|s|kb|mb|gb)?$/i.test(text)) return true;
  return LITERAL_WORDS.has(text.toLowerCase());
}

export function graphNoise(node: { node_type: string; display_name: string }): GraphNoise {
  if (STRUCTURE_NODE_TYPES.has(node.node_type)) return "structure";
  return isLiteralName(node.display_name) ? "literal" : null;
}

/** The nodes a view shows: noise is dropped unless asked for; the centre entity always stays. */
export function withoutNoise<T extends { id: string; node_type: string; display_name: string }>(
  nodes: T[], options: { showNoise: boolean; keepId?: string },
): T[] {
  if (options.showNoise) return nodes;
  return nodes.filter((node) => node.id === options.keepId || graphNoise(node) === null);
}

/**
 * Whether a view would be empty only because every node is noise (a Workspace with documents and chapters but
 * nothing extracted yet). Then the view shows the noise instead of "All entities are hidden".
 */
export function onlyNoise(nodes: { id: string; node_type: string; display_name: string }[]): boolean {
  return nodes.length > 0 && nodes.every((node) => graphNoise(node) !== null);
}

export const ONLY_NOISE_NOTE = "Only documents and chapters so far – shown because nothing else is extracted yet";

/** The node a "Show in graph" name stands for: an exact (case-insensitive) name match, never a partial one. */
export function nodeNamed<T extends { id: string; display_name: string }>(nodes: T[], name: string): T | null {
  const wanted = name.trim().toLowerCase();
  if (!wanted) return null;
  return nodes.find((node) => node.display_name.trim().toLowerCase() === wanted) ?? null;
}
