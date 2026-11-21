// Flow Builder: shared empty values, row types and JSON formatting for the editor modules.
import type { FlowDefinitionJson, FlowValidationReport } from "./flowBuilderTypes";

export type ProjectOption = {
  id: string;
  name: string;
};

export type ToolRow = {
  name: string;
  description?: string;
  is_core?: boolean;
};

export const EMPTY_REPORT: FlowValidationReport = {
  valid: false,
  errors: [],
  warnings: [],
  node_count: 0,
  edge_count: 0,
  node_types: [],
};

export const EMPTY_DEFINITION: FlowDefinitionJson = {
  schema_version: "2.0",
  nodes: [],
  edges: [],
};

export const prettyJson = (value: unknown): string => JSON.stringify(value, null, 2);
