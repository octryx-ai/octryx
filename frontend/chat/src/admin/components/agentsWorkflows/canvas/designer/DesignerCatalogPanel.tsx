// The designer's box catalog (D2b1): every kind of box in plain words. Drag one onto the canvas (it lands where it is
// dropped) or click it (it lands on a free spot and is selected).
import { BOX_DRAG_TYPE } from "../PhasedCanvas";
import { FamilyIcon } from "../PhasedCanvasNodes";
import { nodeFamily } from "../phasedGraphWords";
import { kindName } from "./inspector/labels";
import type { NodeKind } from "./types";

const CATALOG_KINDS: { kind: NodeKind; hint: string }[] = [
  { kind: "phase", hint: "An agent does the work" },
  { kind: "gate", hint: "Checks the work: passed or failed" },
  { kind: "decision", hint: "Branches on a result" },
  { kind: "approval", hint: "A person approves or rejects" },
  { kind: "user_confirmation", hint: "A person confirms or asks for changes" },
  { kind: "user_conversation", hint: "Asks a person a question" },
  { kind: "platform_action", hint: "Jira, branch, push, pull request" },
  { kind: "watch", hint: "Waits for CI, a merge, a status" },
  { kind: "sub_workflow", hint: "Runs another workflow" },
  { kind: "review", hint: "A second agent reviews the change" },
  { kind: "parallel_work", hint: "Several agents work side by side on the coordinator's plan" },
  { kind: "pause", hint: "Waits until a person continues" },
  { kind: "outcome", hint: "The workflow ends here" },
];

export function DesignerCatalogPanel({ onAdd, disabled }: { onAdd: (kind: NodeKind) => void; disabled?: boolean }) {
  return (
    <aside className="dsg__catalog aw-pcanvas" aria-label="Boxes">
      <h3>Boxes</h3>
      <p className="dsg__hint">Drag a box onto the canvas, or click it.</p>
      {CATALOG_KINDS.map(({ kind, hint }) => (
        <button key={kind} type="button" className={`dsg__item aw-pbox--${nodeFamily(kind)}`} draggable={!disabled}
          disabled={disabled} data-testid="designer-catalog-item" data-kind={kind} title={hint}
          onDragStart={(event) => {
            event.dataTransfer.setData(BOX_DRAG_TYPE, kind);
            event.dataTransfer.effectAllowed = "copy";
          }}
          onClick={() => onAdd(kind)}>
          <span className="dsg__item-icon"><FamilyIcon family={nodeFamily(kind)} /></span>
          <span className="dsg__item-text">
            <span className="dsg__item-name">{kindName(kind)}</span>
            <span className="dsg__item-hint">{hint}</span>
          </span>
        </button>
      ))}
    </aside>
  );
}
