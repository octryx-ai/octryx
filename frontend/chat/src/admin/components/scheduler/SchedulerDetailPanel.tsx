import { SidePanel } from "../../../layout/SidePanel";
import { StatusLabel } from "../../../layout/StatusLabel";
import { ActionMenu, type ActionMenuItem } from "../workflowSurfaces/ActionMenu";
import { AdminDetailFacts } from "../AdminDetailFacts";
import { SchedulerWorkerStatus } from "./SchedulerWorkerStatus";
import type { WorkerStatusView } from "./workerApplicationModel";
import type { PanelScheduler } from "../taskTypes";
import { lastRunLine, nextRunLine, schedulerState, startsLine, toggleLabel } from "./schedulerRowWords";

// The side panel of one scheduler: its facts, the worker status with its reason, and the actions (Edit primary,
// Pause or Resume, Delete in the ⋯ menu of the panel header). Rows owned elsewhere are not edited here; they still
// pause, resume and delete.
export function SchedulerDetailPanel({
  scheduler,
  worker,
  onClose,
  onEdit,
  onToggle,
  menuItems,
}: {
  scheduler: PanelScheduler;
  worker: WorkerStatusView;
  onClose: () => void;
  onEdit: () => void;
  onToggle: () => void;
  menuItems: ActionMenuItem[];
}) {
  const state = schedulerState(scheduler, worker);
  return (
    <SidePanel
      title={scheduler.name}
      subtitle="Scheduler"
      onClose={onClose}
      testId="scheduler-detail-panel"
      // Delete sits in the ⋯ menu at the top: a menu in the footer would open below the screen.
      headerActions={<ActionMenu row={{ objectName: scheduler.name }} items={menuItems} />}
      footer={
        <>
          <button type="button" className="admin-panel__action-btn" onClick={onToggle} data-testid="scheduler-panel-toggle">
            {toggleLabel(scheduler)}
          </button>
          {scheduler.read_only ? null : (
            <button
              type="button"
              className="admin-panel__action-btn admin-panel__action-btn--primary"
              onClick={onEdit}
            >
              Edit
            </button>
          )}
        </>
      }
    >
      <AdminDetailFacts
        testId="scheduler-facts"
        facts={[
          { label: "State", value: <StatusLabel label={state.label} tone={state.tone} /> },
          { label: "Description", value: scheduler.description },
          { label: "Starts", value: startsLine(scheduler) },
          { label: "Runs", value: scheduler.schedule_words || scheduler.cron_expression },
          { label: "Next run", value: nextRunLine(scheduler, worker) },
          { label: "Last run", value: lastRunLine(scheduler) },
          { label: "Worker", value: <SchedulerWorkerStatus view={worker} /> },
          {
            label: "Managed in",
            value: scheduler.read_only
              ? scheduler.managed_by_work
                ? "Work › Intake"
                : "The action's own schedule"
              : "",
          },
        ]}
      />
    </SidePanel>
  );
}
