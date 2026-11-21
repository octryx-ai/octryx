import { memo, useMemo } from "react";
import { Handle, Position } from "@xyflow/react";
import type { FlowDefinitionNode } from "./flowBuilderTypes";

type FlowNodeData = FlowDefinitionNode & {
  selected?: boolean;
  agentName?: string;
  toolNames?: string[];
  triggerType?: string;
  runStatus?: string;
  // A phase's steps and checks (agentsWorkflows/canvas) name their own sub-label and badges.
  subLabel?: string;
  badges?: { label: string; kind: string }[];
};

function shortType(value: string): string {
  return value.replaceAll("_", " ");
}

function statusClass(status?: string): string {
  if (!status) return "";
  return `flow-node--run-${status}`;
}

const TYPE_SUB_LABELS: Record<string, string> = {
  trigger: "Trigger",
  input_schema: "Input",
  policy_gate: "Policy",
  clarification_gate: "Clarification",
  retrieval: "Retrieval",
  router: "If / else",
  agent_step: "Agent",
  tool_step: "Tool",
  approval: "Approval",
  evaluation: "Evaluation",
  parallel: "Parallel",
  join: "Join",
  human_task: "Task",
  output: "Output",
  learning_proposal: "Learning",
  error_handler: "Error",
  supervisor: "Supervisor",
};

// The sub-label from the system reference: the agent, the tools, the trigger, else the step type.
function subLabelOf(data: Pick<FlowNodeData, "subLabel" | "type" | "agentName" | "toolNames" | "triggerType">): string {
  if (data.subLabel) return data.subLabel;
  if (data.type === "agent_step" && data.agentName) {
    return "Agent";
  }
  if (
    data.type === "tool_step" &&
    data.toolNames &&
    data.toolNames.length > 0
  ) {
    return data.toolNames.join(", ");
  }
  if (data.type === "trigger" && data.triggerType) {
    return data.triggerType;
  }
  return TYPE_SUB_LABELS[data.type] ?? shortType(data.type);
}

function flowNodeClassName(data: FlowNodeData, isSelected: boolean | undefined): string {
  const hasAgentRef = data.type === "agent_step" && Boolean(data.agentName);
  const hasToolRef =
    data.type === "tool_step" &&
    Boolean(data.toolNames && data.toolNames.length > 0);
  const hasTriggerRef = data.type === "trigger" && Boolean(data.triggerType);
  return [
    "flow-node",
    isSelected ? "flow-node--selected" : "",
    hasAgentRef ? "flow-node--agent-ref" : "",
    hasToolRef ? "flow-node--tool-ref" : "",
    hasTriggerRef ? "flow-node--trigger-ref" : "",
    statusClass(data.runStatus),
  ]
    .filter(Boolean)
    .join(" ");
}

function FlowNodeBadges({ badges }: { badges: NonNullable<FlowNodeData["badges"]> }) {
  return (
    <div className="flow-node__badges">
      {badges.map((badge) => (
        <span key={badge.label} className={`work-badge work-badge--${badge.kind}`}>{badge.label}</span>
      ))}
    </div>
  );
}

function FlowNodeSchemas({ inputKeys, outputKeys }: { inputKeys: string[]; outputKeys: string[] }) {
  return (
    <div className="flow-node__schemas">
      {inputKeys.length > 0 ? (
        <div className="flow-node__schema">
          <span className="flow-node__schema-label">in</span>
          <code className="flow-node__schema-keys">
            {inputKeys.join(", ") || "—"}
          </code>
        </div>
      ) : null}
      {outputKeys.length > 0 ? (
        <div className="flow-node__schema">
          <span className="flow-node__schema-label">out</span>
          <code className="flow-node__schema-keys">
            {outputKeys.join(", ") || "—"}
          </code>
        </div>
      ) : null}
    </div>
  );
}

export const FlowNode = memo(function FlowNode({
  data,
  selected,
}: {
  data: FlowNodeData;
  selected?: boolean;
}) {
  const isSelected = selected || data.selected;

  const inputKeys = useMemo(
    () => (data.input_schema ? Object.keys(data.input_schema) : []),
    [data.input_schema],
  );
  const outputKeys = useMemo(
    () => (data.output_schema ? Object.keys(data.output_schema) : []),
    [data.output_schema],
  );

  // Resolve display label and sub-label based on system reference
  const displayLabel = useMemo(() => {
    if (data.type === "agent_step" && data.agentName) {
      return data.agentName;
    }
    return data.label || data.id;
  }, [data.type, data.agentName, data.label, data.id]);

  const displaySubLabel = useMemo(() => subLabelOf({ subLabel: data.subLabel, type: data.type, agentName: data.agentName, toolNames: data.toolNames, triggerType: data.triggerType }), [data.subLabel, data.type, data.agentName, data.toolNames, data.triggerType]);

  return (
    <div className={flowNodeClassName(data, isSelected)}>
      <Handle type="target" position={Position.Left} className="flow-node__handle" />

      <div className="flow-node__header">
        <span className="flow-node__label">{displayLabel}</span>
        {data.runStatus ? (
          <span className="flow-node__run-status" title={`Latest run: ${data.runStatus}`} />
        ) : null}
      </div>

      <div className="flow-node__sub-label">{displaySubLabel}</div>
      {data.badges?.length ? <FlowNodeBadges badges={data.badges} /> : null}

      {inputKeys.length > 0 || outputKeys.length > 0 ? (
        <FlowNodeSchemas inputKeys={inputKeys} outputKeys={outputKeys} />
      ) : null}

      <Handle type="source" position={Position.Right} className="flow-node__handle" />
    </div>
  );
});
