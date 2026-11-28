export const STRUCTURE_NODE_TYPES: ReadonlySet<string> = new Set(["Document", "Chapter", "Section", "ConfigFile"]);

const LITERAL_WORDS: ReadonlySet<string> = new Set([
  "true", "false", "yes", "no", "on", "off", "null", "none", "nil", "undefined", "n/a", "na", "default", "empty",
]);

export type GraphNoise = "structure" | "literal" | null;

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

export function withoutNoise<T extends { id: string; node_type: string; display_name: string }>(
  nodes: T[], options: { showNoise: boolean; keepId?: string },
): T[] {
  if (options.showNoise) return nodes;
  return nodes.filter((node) => node.id === options.keepId || graphNoise(node) === null);
}

export function onlyNoise(nodes: { id: string; node_type: string; display_name: string }[]): boolean {
  return nodes.length > 0 && nodes.every((node) => graphNoise(node) !== null);
}

export const ONLY_NOISE_NOTE = "Only documents and chapters so far – shown because nothing else is extracted yet";

export function nodeNamed<T extends { id: string; display_name: string }>(nodes: T[], name: string): T | null {
  const wanted = name.trim().toLowerCase();
  if (!wanted) return null;
  return nodes.find((node) => node.display_name.trim().toLowerCase() === wanted) ?? null;
}
