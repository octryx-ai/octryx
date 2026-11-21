import { AdminHeaderActions } from "./AdminHeaderSlot";
import type { AdminTasksTabCtx } from "./AdminTasksTab.types";

type AdminTasksTabHeaderProps = {
  ctx: AdminTasksTabCtx;
};

export function AdminTasksTabHeader({ ctx }: AdminTasksTabHeaderProps) {
  const { tasks, onOpenTaskForm } = ctx;
  const activeCount = tasks.filter((task) => task.is_active).length;
  const runningCount = tasks.filter((task) => task.running_count > 0).length;
  const queuedCount = tasks.reduce(
    (sum, task) => sum + (task.queued_count || 0),
    0,
  );

  return (
    <>
      {/* The counts in one quiet line (no uppercase eyebrow above the table). */}
      <p className="admin-panel__cell--muted admin-tasks__summary" data-testid="actions-summary">
        {activeCount} active · {runningCount} running · {queuedCount} queued
      </p>
      {/* New action always opens the clean form in a side panel; it never turns into Cancel.
          What an action, a scheduler and a workflow are is in the page help (help/admin/tasks.md). */}
      <AdminHeaderActions>
        <button
          type="button"
          className="admin-panel__action-btn admin-panel__action-btn--primary"
          onClick={() => onOpenTaskForm()}
          data-testid="action-new"
        >
          New action
        </button>
      </AdminHeaderActions>
    </>
  );
}
