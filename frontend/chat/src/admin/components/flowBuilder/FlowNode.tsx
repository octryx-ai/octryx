import { memo } from "react";
import { Handle, Position } from "@xyflow/react";
import type { FlowDefinitionNode } from "./flowBuilderTypes";

type FlowNodeData = FlowDefinitionNode & {
  selected?: boolean;
  subLabel: string;
  badges?: { label: string; kind: string }[];
};

function FlowNodeBadges({ badges }: { badges: NonNullable<FlowNodeData["badges"]> }) {
  return (
    <div className="flow-node__badges">
      {badges.map((badge) => (
        <span key={badge.label} className={`work-badge work-badge--${badge.kind}`}>{badge.label}</span>
      ))}
    </div>
  );
}

export const FlowNode = memo(function FlowNode({ data, selected }: { data: FlowNodeData; selected?: boolean }) {
  const isSelected = selected || data.selected;
  return (
    <div className={isSelected ? "flow-node flow-node--selected" : "flow-node"}>
      <Handle type="target" position={Position.Left} className="flow-node__handle" />
      <div className="flow-node__header">
        <span className="flow-node__label">{data.label || data.id}</span>
      </div>
      <div className="flow-node__sub-label">{data.subLabel}</div>
      {data.badges?.length ? <FlowNodeBadges badges={data.badges} /> : null}
      <Handle type="source" position={Position.Right} className="flow-node__handle" />
    </div>
  );
});
