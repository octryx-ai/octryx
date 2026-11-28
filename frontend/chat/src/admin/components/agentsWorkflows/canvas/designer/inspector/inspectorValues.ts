// Value readers and shared props for the node inspector forms.
import type { DefEdge, DefNode, DesignerCatalog, FieldIssue } from "../types";
import { kindName, toolName } from "./labels";

export type Config = Record<string, unknown>;

export const text = (value: unknown) => (typeof value === "string" ? value : "");
export const record = (value: unknown): Config =>
  value && typeof value === "object" && !Array.isArray(value) ? (value as Config) : {};
export const strings = (value: unknown) => (Array.isArray(value) ? value.filter((item): item is string => typeof item === "string") : []);
export const objects = (value: unknown) => (Array.isArray(value) ? value.map(record) : []);
export const boxName = (node: DefNode | undefined) => (node ? node.label || kindName(node.type) : "");

export const toolChoices = (catalog: DesignerCatalog) =>
  catalog.tools.map((tool) => ({ value: tool, label: toolName(tool) })).sort((a, b) => a.label.localeCompare(b.label));

export type FormProps = {
  node: DefNode; nodes: DefNode[]; edges: DefEdge[]; catalog: DesignerCatalog; editable: boolean; issues: FieldIssue[];
  set: (path: string, value: unknown) => void;
  setAll: (changes: [string, unknown][]) => void;
  replace: (config: Config) => void;
  onRoute?: (when: string, target: string | null) => void;
};
