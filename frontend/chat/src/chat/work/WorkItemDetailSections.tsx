// Sections of the Work Item detail: the start form, the Activity tab and the header actions.
import type { WorkItem } from "./workItemTypes";
import type { WorkWorkflowDefinition } from "./workSyncWorkflowTypes";
import { WorkItemStateTimeline } from "./WorkItemStateTimeline";
import { WorkItemTransition } from "./WorkItemTransition";
import { WorkItemRunStart } from "./WorkItemRunStart";
import { WorkItemHeaderActions } from "./WorkItemHeaderActions";
import { asArray } from "./workItemDetailValues";
import { DetailSection, ExternalActivity } from "./WorkItemDetailParts";
import { START_SECTION_ID } from "./workItemStartSection";

type StartProps = {
  item: WorkItem;
  workflows: WorkWorkflowDefinition[];
  actionLabel: string;
  closed: boolean;
  movable: boolean;
  onCancel: () => void;
  onApplied: () => void;
};

// Only after "Start workflow": the run form, and (when a workflow covers the item) the move to another state.
export function WorkItemStartSection({ item, workflows, actionLabel, closed, movable, onCancel, onApplied }: StartProps) {
  return (
    <section className="work-detail__section work-detail__start" id={START_SECTION_ID} role="group"
      aria-label={actionLabel} data-testid="work-item-start-section">
      <div className="work-detail__start-head">
        <h3>{actionLabel}</h3>
        <button type="button" className="work-area__button" onClick={onCancel} data-testid="work-item-start-cancel">
          Cancel
        </button>
      </div>
      {closed ? null : <WorkItemRunStart key={item.id} item={item} focusOnOpen />}
      {movable ? (
        <>
          {/* Move the item to another workflow state; the confirmation shows what is written to Jira. */}
          {closed ? null : <h4>Move to another state</h4>}
          <WorkItemTransition key={item.id} item={item} workflows={workflows} onApplied={onApplied} />
        </>
      ) : null}
    </section>
  );
}

type ActivityProps = { item: WorkItem; workflows: WorkWorkflowDefinition[]; timelineKey: number };

export function WorkItemActivityTab({ item, workflows, timelineKey }: ActivityProps) {
  return (
    <>
      <DetailSection title="Audit timeline">
        <WorkItemStateTimeline workItemId={item.id} reloadKey={timelineKey} workflows={workflows} />
      </DetailSection>
      <DetailSection title="External Activity">
        <ExternalActivity values={asArray(item.source_fields?.external_activity)} />
      </DetailSection>
    </>
  );
}

type HeaderProps = {
  item: WorkItem;
  onClosed: () => void;
  showStart: boolean;
  closed: boolean;
  starting: boolean;
  actionLabel: string;
  onStart: () => void;
  backButton: boolean;
  onBack: () => void;
};

export function WorkItemDetailHeaderActions({ item, onClosed, showStart, closed, starting, actionLabel, onStart, backButton, onBack }: HeaderProps) {
  return (
    <WorkItemHeaderActions item={item} onClosed={onClosed}>
      {showStart ? (
        <button type="button" className={`admin-panel__action-btn${closed ? "" : " admin-panel__action-btn--primary"}`}
          onClick={onStart} aria-expanded={starting} aria-controls={starting ? START_SECTION_ID : undefined} data-testid="work-item-start-workflow">
          {actionLabel}
        </button>
      ) : null}
      {backButton ? (
        <button type="button" className="admin-panel__action-btn" onClick={onBack} data-testid="work-item-back">
          ← All work items
        </button>
      ) : null}
    </WorkItemHeaderActions>
  );
}
