import { useState } from "react";
import { useAdminNavigation } from "../adminNavigation";
import { useSchedulerPreview } from "../hooks/useSchedulerPreview";
import { scheduleSubmitGate } from "./scheduler/scheduleModel";
import { SchedulerStatusCheckBar } from "./scheduler/SchedulerWorkerStatus";
import { useSchedulerStatusCheck } from "./scheduler/useSchedulerStatusCheck";
import { presentWorkerApplication } from "./scheduler/workerApplicationModel";
import type { PanelScheduler } from "./taskTypes";
import "./adminSchedulers.css";
import { useConfirmAction } from "./confirm/useConfirmAction";
import { AdminHeaderActions } from "./AdminHeaderSlot";
import { EmptyLine } from "../../layout/EmptyLine";
import { ActionMenu, type ActionMenuItem } from "./workflowSurfaces/ActionMenu";
import { DataTable, type DataTableColumn } from "../../layout/DataTable";
import { StatusLabel } from "../../layout/StatusLabel";
import type { AdminSchedulersTabCtx } from "./scheduler/schedulersTabTypes";
import { deleteQuestion, nextRunLine, schedulerState, startsLine, toggleLabel } from "./scheduler/schedulerRowWords";
import { SchedulerDetailPanel } from "./scheduler/SchedulerDetailPanel";
import { SchedulerFormPanel } from "./scheduler/SchedulerFormPanel";

type AdminSchedulersTabProps = {
  ctx: Record<string, unknown>;
};

function schedulerMenuItems(
  scheduler: PanelScheduler, withEdit: boolean, { onOpenSchedulerForm, onToggleScheduler }: AdminSchedulersTabCtx,
  askDelete: (scheduler: PanelScheduler) => void,
): ActionMenuItem[] {
  return [
    ...(withEdit && !scheduler.read_only ? [{ label: "Edit", onSelect: () => onOpenSchedulerForm(scheduler) }] : []),
    {
      label: toggleLabel(scheduler),
      onSelect: () => void onToggleScheduler(scheduler.id, scheduler.is_active),
      testId: `scheduler-toggle-${scheduler.id}`,
    },
    { label: "Delete…", danger: true, onSelect: () => askDelete(scheduler), testId: `scheduler-delete-${scheduler.id}` },
  ];
}

export function AdminSchedulersTab({ ctx }: AdminSchedulersTabProps) {
  const {
    schedulers, setSchedulers, tasks, showSchedulerForm, onCreateScheduler, onOpenSchedulerForm, onToggleScheduler,
    onDeleteScheduler,
  } = ctx as AdminSchedulersTabCtx;
  // The scheduler whose side panel is open (details and actions); it follows the list by id.
  const [openId, setOpenId] = useState<string | null>(null);
  const statusCheck = useSchedulerStatusCheck(schedulers, setSchedulers);
  const now = new Date();
  const { preview, retry } = useSchedulerPreview(
    (ctx as AdminSchedulersTabCtx).schedulerFormCron,
    showSchedulerForm,
  );
  const openScheduler = schedulers.find((scheduler) => scheduler.id === openId) ?? null;
  // Delete sits in the row's ⋯ menu and is confirmed in the app, naming the scheduler.
  const { ask, dialog, notice } = useConfirmAction();
  const askDelete = (scheduler: PanelScheduler) => ask(deleteQuestion(scheduler, onDeleteScheduler));
  // Every row has its ⋯ menu. Rows owned by Work › Intake or stored on an Action are not edited
  // here, but they can be paused, resumed and deleted through the existing scheduler and Action APIs.
  const menuItems = (scheduler: PanelScheduler, withEdit: boolean) =>
    schedulerMenuItems(scheduler, withEdit, ctx as AdminSchedulersTabCtx, askDelete);

  return (
    <div>
      {notice}
      {dialog}
      {/* Create and edit open in a side panel over the list. */}
      <SchedulersHeader ctx={ctx as AdminSchedulersTabCtx} statusCheck={statusCheck} />

      {showSchedulerForm ? <SchedulerForm ctx={ctx as AdminSchedulersTabCtx} preview={preview} retry={retry} /> : null}

      {schedulers.length === 0 ? (
        tasks.length > 0 ? (
          <EmptyLine
            text="No schedulers yet."
            action={{ label: "New scheduler", onClick: onCreateScheduler }}
            testId="scheduler-empty"
          />
        ) : null
      ) : (
        // A full-width table; the name column takes the remaining width (it was about 60 px).
        <SchedulersTable schedulers={schedulers} showSchedulerForm={showSchedulerForm} openId={openId} setOpenId={setOpenId}
          now={now} menuItems={menuItems} />
      )}

      {openScheduler && !showSchedulerForm ? (
        <SchedulerDetailPanel
          scheduler={openScheduler}
          worker={presentWorkerApplication(openScheduler.worker_application, now)}
          onClose={() => setOpenId(null)}
          onEdit={() => { setOpenId(null); onOpenSchedulerForm(openScheduler); }}
          onToggle={() => void onToggleScheduler(openScheduler.id, openScheduler.is_active)}
          menuItems={menuItems(openScheduler, false).filter((item) => item.danger)}
        />
      ) : null}
    </div>
  );
}

// The table's columns; the next run and the state are read against `now`.
function schedulerColumns(now: Date): DataTableColumn<PanelScheduler>[] {
  return [
    {
      key: "name",
      header: "Name",
      grow: true,
      minWidth: "12rem",
      render: (scheduler) => (
        <span title={scheduler.description || undefined}>{scheduler.name}</span>
      ),
    },
    { key: "starts", header: "Starts", nowrap: true, clip: "18rem", render: (scheduler) => <span title={startsLine(scheduler)}>{startsLine(scheduler)}</span> },
    {
      key: "runs",
      header: "Runs",
      nowrap: true,
      render: (scheduler) => (
        <span title={scheduler.cron_expression}>
          {scheduler.schedule_words || scheduler.cron_expression}
        </span>
      ),
    },
    {
      key: "next",
      header: "Next run",
      nowrap: true,
      render: (scheduler) =>
        nextRunLine(scheduler, presentWorkerApplication(scheduler.worker_application, now)),
    },
    {
      key: "state",
      header: "State",
      nowrap: true,
      render: (scheduler) => {
        const worker = presentWorkerApplication(scheduler.worker_application, now);
        const state = schedulerState(scheduler, worker);
        return (
          <StatusLabel
            label={state.label}
            tone={state.tone}
            title={scheduler.is_active ? worker.detail : undefined}
            testId={`scheduler-state-${scheduler.id}`}
          />
        );
      },
    },
  ];
}

type TableProps = {
  schedulers: PanelScheduler[]; showSchedulerForm: boolean; openId: string | null; setOpenId: (id: string | null) => void;
  now: Date; menuItems: (scheduler: PanelScheduler, withEdit: boolean) => ActionMenuItem[];
};

function SchedulersTable({ schedulers, showSchedulerForm, openId, setOpenId, now, menuItems }: TableProps) {
  return (
    <DataTable<PanelScheduler>
      label="Schedulers"
      testId="schedulers-table"
      rows={schedulers}
      rowKey={(scheduler) => scheduler.id}
      onOpen={(scheduler) => setOpenId(scheduler.id)}
      selectedKey={showSchedulerForm ? null : openId}
      columns={schedulerColumns(now)}
      rowMenu={(scheduler) => (
        <ActionMenu row={{ objectName: scheduler.name }} items={menuItems(scheduler, true)} />
      )}
    />
  );
}

type FormProps = { ctx: AdminSchedulersTabCtx } & Pick<ReturnType<typeof useSchedulerPreview>, "preview" | "retry">;

function SchedulerForm({ ctx, preview, retry }: FormProps) {
  const {
    tasks, editingScheduler, schedulerFormName, setSchedulerFormName, schedulerFormDesc, setSchedulerFormDesc,
    schedulerFormCron, setSchedulerFormCron, schedulerFormTaskId, setSchedulerFormTaskId, schedulerFormLoading,
    schedulerFormError, onCloseSchedulerForm, onSaveScheduler,
  } = ctx;
  const gate = scheduleSubmitGate(
    editingScheduler ? editingScheduler.cron_expression : null,
    schedulerFormCron,
    preview,
  );
  const chosenAction = tasks.find((task) => task.id === schedulerFormTaskId);
  return (
    <SchedulerFormPanel tasks={tasks} editingScheduler={editingScheduler} schedulerFormName={schedulerFormName}
      setSchedulerFormName={setSchedulerFormName} schedulerFormDesc={schedulerFormDesc} setSchedulerFormDesc={setSchedulerFormDesc}
      schedulerFormCron={schedulerFormCron} setSchedulerFormCron={setSchedulerFormCron} schedulerFormTaskId={schedulerFormTaskId}
      setSchedulerFormTaskId={setSchedulerFormTaskId} schedulerFormLoading={schedulerFormLoading} schedulerFormError={schedulerFormError}
      onCloseSchedulerForm={onCloseSchedulerForm} onSaveScheduler={onSaveScheduler} preview={preview} retry={retry} gate={gate}
      chosenAction={chosenAction} />
  );
}

type HeaderProps = { ctx: AdminSchedulersTabCtx; statusCheck: ReturnType<typeof useSchedulerStatusCheck> };

function SchedulersHeader({ ctx: { schedulers, tasks, onCreateScheduler }, statusCheck }: HeaderProps) {
  const { openAdminTab } = useAdminNavigation();
  return (
    <>
    <AdminHeaderActions>
      <button
        type="button"
        className="admin-panel__action-btn admin-panel__action-btn--primary"
        onClick={onCreateScheduler}
        disabled={tasks.length === 0}
        data-testid="scheduler-new"
      >
        New scheduler
      </button>
    </AdminHeaderActions>
    {schedulers.length > 0 ? (
      <SchedulerStatusCheckBar
        status={statusCheck}
        onCheck={() => void statusCheck.check()}
      />
    ) : null}
    {tasks.length === 0 ? (
      <EmptyLine
        text="No actions yet; a scheduler needs one to run."
        action={{ label: "Open actions", onClick: () => openAdminTab("tasks") }}
        testId="scheduler-needs-action"
      />
    ) : null}
    </>
  );
}
