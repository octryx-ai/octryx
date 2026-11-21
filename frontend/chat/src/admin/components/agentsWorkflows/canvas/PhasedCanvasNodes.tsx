// The phased canvas's custom React Flow nodes and edge: a box, a group frame, an arrow, and the family icons.
import { memo } from "react";
import {
  BaseEdge,
  EdgeLabelRenderer,
  Handle,
  Position,
  useConnection,
  type Edge,
  type EdgeProps,
  type Node,
  type NodeProps,
} from "@xyflow/react";
import type { NodeFamily } from "./phasedGraphTypes";
import type { ArrowData, BoxData, GroupData } from "./phasedCanvasTypes";

const ICONS: Record<NodeFamily, string> = {
  start: "M5 3l8 5-8 5z",
  agent: "M4 6h8v7H4z M8 3v3 M6.5 9.5h.01 M9.5 9.5h.01",
  // Fork and join: one way in, several side by side, one way out.
  parallel: "M8 1v3 M8 4L3 7v2l5 3 M8 4l5 3v2l-5 3 M8 4v8 M8 12v3",
  action: "M9 1L3 9h4l-1 6 6-8H8z",
  person: "M8 8a3 3 0 1 0 0-6 3 3 0 0 0 0 6z M2 15c0-3 3-5 6-5s6 2 6 5",
  wait: "M8 2a6 6 0 1 0 0 12A6 6 0 0 0 8 2z M8 5v3l2 2",
  check: "M8 1l6 2v5c0 4-3 6-6 7-3-1-6-3-6-7V3z M5.5 8l2 2 3-3.5",
  decision: "M8 1l7 7-7 7-7-7z",
  subflow: "M2 5h9v9H2z M5 2h9v9",
  end: "M3 15V2 M3 2h9l-2 3 2 3H3",
};

export function FamilyIcon({ family }: { family: NodeFamily }) {
  return (
    <svg className="aw-pbox__icon" viewBox="0 0 16 16" width="14" height="14" aria-hidden="true">
      <path d={ICONS[family]} />
    </svg>
  );
}

// The fold control's chevron: down while the group is open, right while it is one box.
function Chevron({ open }: { open: boolean }) {
  return (
    <svg viewBox="0 0 12 12" width="10" height="10" aria-hidden="true">
      <path d={open ? "M2.5 4.5l3.5 3.5 3.5-3.5" : "M4.5 2.5l3.5 3.5-3.5 3.5"} fill="none" stroke="currentColor" strokeWidth="1.6"
        strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

function BoxBadges({ data }: { data: BoxData }) {
  if (!data.badges.length) return null;
  return (
    <span className="aw-pbox__badges">
      {data.badges.map((badge) => (
        <button key={`${badge.tone}-${badge.label}-${badge.edgeIds[0] ?? ""}`} type="button" className={`aw-pbadge aw-pbadge--${badge.tone} nodrag`}
          title={data.editing ? `${badge.title}. Click to change this arrow.` : `${badge.title}. Click to see that box.`}
          {...(data.editing ? {
            "data-testid": "designer-edge", "data-edge-id": badge.edgeIds[0], "data-source": data.id, "data-target": badge.target,
            "data-when": badge.when ?? "",
          } : {})}
          onClick={(event) => { event.stopPropagation(); data.onBadge(badge.target, badge.edgeIds); }}>
          {badge.label}
        </button>
      ))}
    </span>
  );
}

export const PhasedBox = memo(function PhasedBox({ data, selected }: NodeProps<Node<BoxData>>) {
  // While an arrow is being drawn, the whole box takes it (not only the small port at its edge).
  const connecting = useConnection((connection) => connection.inProgress);
  const className = [
    "aw-pbox",
    `aw-pbox--${data.family}`,
    data.kind === "group" ? "aw-pbox--folded" : "",
    data.goodEnd ? "aw-pbox--good" : "",
    data.aside ? "aw-pbox--aside" : "",
    selected ? "is-selected" : "",
  ].filter(Boolean).join(" ");
  return (
    <div className={className} style={{ height: data.height }} data-testid="designer-node" data-node-id={data.id}
      data-kind={data.kind} onDoubleClick={data.onUnfold ?? data.onOpen}>
      <Handle type="target" position={data.lr ? Position.Left : Position.Top}
        className={`aw-pbox__handle${data.editing && connecting ? " aw-pbox__handle--drop" : ""}`} isConnectable={data.editing} />
      {data.kindLine ? (
        <span className="aw-pbox__kind">
          <FamilyIcon family={data.family} />
          {data.kindLine}
          {data.onUnfold ? (
            <button type="button" className="aw-pgroup__toggle nodrag" aria-label={`Unfold ${data.title}`} title="Unfold the group"
              onClick={(event) => { event.stopPropagation(); data.onUnfold?.(); }}><Chevron open={false} /></button>
          ) : null}
        </span>
      ) : null}
      <strong className="aw-pbox__title" title={data.title}>
        {data.kindLine ? null : <FamilyIcon family={data.family} />}
        {data.title}
      </strong>
      {data.subtitle ? <span className="aw-pbox__sub" title={data.subtitle}>{data.subtitle}</span> : null}
      <BoxBadges data={data} />
      {data.onMenu ? (
        <button type="button" className="aw-pbox__menu nodrag" data-testid="designer-node-menu" aria-label={`More for ${data.title}`}
          title="Connect, copy or delete" onClick={(event) => { event.stopPropagation(); data.onMenu?.(); }}>⋯</button>
      ) : null}
      <Handle type="source" position={data.lr ? Position.Right : Position.Bottom}
        className={`aw-pbox__handle${data.editing ? " aw-pbox__port" : ""}`} isConnectable={data.editing}
        {...(data.editing ? { "data-testid": "designer-port-out", title: "Drag to the next box" } : {})} />
    </div>
  );
});

// An unfolded group: a frame behind its boxes with the fold control and how many boxes it holds (a phase's box names
// its group; a run of steps and a hand-made group say their name).
export const PhasedGroup = memo(function PhasedGroup({ data }: NodeProps<Node<GroupData>>) {
  const count = data.kind === "steps" ? `${data.count} steps` : `${data.count} boxes`;
  const said = data.kind === "phase" || !data.kind ? count : `${data.title} · ${count}`;
  return (
    <div className="aw-pgroup">
      <span className="aw-pgroup__head" title={`${data.title}: ${count}`}>
        <button type="button" className="aw-pgroup__toggle nodrag" aria-label={`Fold ${data.title}`} title="Fold into one box"
          onClick={(event) => { event.stopPropagation(); data.onFold(); }}><Chevron open /></button>
        <span className="aw-pgroup__title">{said}</span>
        {data.onEdit ? (
          <button type="button" className="aw-pgroup__edit nodrag" data-testid="designer-group-edit" aria-label={`Rename or ungroup ${data.title}`}
            title="Rename or ungroup" onClick={(event) => { event.stopPropagation(); data.onEdit?.(); }}>Edit</button>
        ) : null}
      </span>
    </div>
  );
});

export const PhasedArrow = memo(function PhasedArrow({ id, data }: EdgeProps<Edge<ArrowData>>) {
  if (!data) return null;
  const className = `aw-parrow aw-parrow--${data.tone}${data.aside ? " aw-parrow--aside" : ""}${data.selected ? " is-selected" : ""}`;
  return (
    <>
      <BaseEdge id={id} path={data.d} className={className} markerEnd={`url(#aw-arrowhead-${data.tone})`} interactionWidth={14} />
      {data.editing ? (
        <EdgeLabelRenderer>
          <button type="button" className={`aw-parrow__chip aw-parrow__label--${data.tone} nodrag nopan${data.selected ? " is-selected" : ""}`}
            style={{ transform: `translate(-50%, -50%) translate(${data.at.x}px, ${data.at.y}px)` }}
            data-testid="designer-edge" data-edge-id={id} data-source={data.source} data-target={data.target} data-when={data.when ?? ""}
            title={data.title || "Click to change this arrow"} onClick={(event) => { event.stopPropagation(); data.onSelect?.(); }}>
            {data.label || "→"}
          </button>
        </EdgeLabelRenderer>
      ) : data.label && !data.aside ? (
        <EdgeLabelRenderer>
          <span
            className={`aw-parrow__label aw-parrow__label--${data.tone}`}
            style={{ transform: `translate(-50%, -50%) translate(${data.at.x}px, ${data.at.y}px)` }}
            title={data.title || undefined}
          >
            {data.label}
          </span>
        </EdgeLabelRenderer>
      ) : null}
    </>
  );
});
