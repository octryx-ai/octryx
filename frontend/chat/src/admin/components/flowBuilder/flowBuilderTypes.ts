// The node and edge shapes the steps canvas draws (see agentsWorkflows/canvas/stepsGraphModel.ts).
export type FlowNodeType = "trigger" | "approval" | "tool_step" | "evaluation" | "output";

export type FlowDefinitionNode = {
  id: string;
  type: FlowNodeType;
  label?: string;
};

export type FlowDefinitionEdge = {
  id: string;
  from_node_id: string;
  to_node_id: string;
};
