// Side panel of a box in the phased workflow chart: who runs it, its rules, checks, exits and loops.
import { AdvancedSection, FormSection } from "../../../../layout/FormSection";
import { SidePanel } from "../../../../layout/SidePanel";
import { StatusLabel, type StatusTone } from "../../../../layout/StatusLabel";
import type { EdgeTone } from "./phasedGraphTypes";
import type { NodeDetails } from "./phasedNodeDetails";
import type { PhasedNode } from "./phasedWorkflowModel";

const EXIT_TONES: Record<EdgeTone, StatusTone> = { success: "success", failure: "problem", neutral: "neutral", loop: "attention" };

type Props = {
  selected: PhasedNode;
  details: NodeDetails;
  unsavedLayout: boolean;
  onClose: () => void;
  onOpenSteps: () => void;
};

export function PhasedNodePanel({ selected, details, unsavedLayout, onClose, onOpenSteps }: Props) {
  return (
    <SidePanel
      title={selected.title || selected.id}
      subtitle={details.kindLabel}
      onClose={onClose}
      testId="phased-node-panel"
      size="narrow"
      footer={(
        <>
          {selected.kind === "phase" ? (
            <button type="button" className="admin-panel__action-btn" disabled={unsavedLayout}
              title={unsavedLayout ? "Save or undo the moved boxes first" : "Open this phase's steps and checks"}
              onClick={onOpenSteps}>
              Open steps
            </button>
          ) : null}
          <button type="button" className="admin-panel__action-btn admin-panel__action-btn--primary" onClick={onClose}>
            Done
          </button>
        </>
      )}
    >
      <div className="aw-pnode">
        <FormSection title="Who runs it">
          <p className="aw-pnode__who">{details.who}</p>
          {details.what ? <p className="aw-pnode__what">{details.what}</p> : null}
        </FormSection>
        {details.rules.length ? (
          <FormSection title="What it may do">
            <ul className="aw-pnode__list">
              {details.rules.map((rule) => <li key={rule}>{rule}</li>)}
            </ul>
          </FormSection>
        ) : null}
        {details.checks.length ? (
          <FormSection title={selected.kind === "gate" ? "Passes when" : "Done when"}>
            <ul className="aw-pnode__list">
              {details.checks.map((check, index) => (
                <li key={`${index}-${check.label}`} className="aw-pnode__row">
                  <span>{check.label}</span>
                  <StatusLabel label={check.blocking ? "Required" : "Reminder"} tone="neutral" />
                </li>
              ))}
            </ul>
          </FormSection>
        ) : null}
        {details.exits.length ? (
          <FormSection title="What happens next">
            <ul className="aw-pnode__list aw-pnode__exits">
              {details.exits.map((exit, index) => (
                <li key={`${index}-${exit.label}-${exit.target}`} className="aw-pnode__exit">
                  <StatusLabel label={exit.label} tone={EXIT_TONES[exit.tone]} />
                  <span className="aw-pnode__exit-target">{exit.loop ? "back to" : "→"} {exit.target}</span>
                </li>
              ))}
            </ul>
          </FormSection>
        ) : null}
        {details.loopsIn.length ? (
          <FormSection title="Comes back here">
            <ul className="aw-pnode__list">
              {details.loopsIn.map((line) => <li key={line}>{line}</li>)}
            </ul>
          </FormSection>
        ) : null}
        <AdvancedSection label="Details" testId="phased-node-details">
          <pre className="aw-pnode__raw">{JSON.stringify({ id: selected.id, kind: selected.kind, ...details.raw }, null, 2)}</pre>
        </AdvancedSection>
      </div>
    </SidePanel>
  );
}
