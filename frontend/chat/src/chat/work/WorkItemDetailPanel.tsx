import { useState, type ReactNode } from "react";
import { useCanManageWork } from "./workAccess";

import type { WorkItem } from "./workItemTypes";
import type { WorkWorkflowDefinition } from "./workSyncWorkflowTypes";
import { ExceptionBadges } from "./WorkAreaViews";
import { workItemDetailStatus, workItemExceptions } from "./workItemExceptions";
import { WorkChangePlans } from "./WorkChangePlans";
import { WorkReviewerRecommendations } from "./WorkReviewerRecommendations";
import { WorkItemJiraSource } from "./WorkItemJiraSource";
import { WorkItemAnalysis } from "./incident/WorkItemAnalysis";
import { WorkItemServiceNowSource } from "./incident/WorkItemServiceNowSource";
import { isServiceNowItem } from "./incident/workSourceModel";
import { WorkItemRuns } from "./WorkItemRuns";
import { TaskList } from "../workflowRun/TaskList";
import { taskProgress } from "../workflowRun/taskListModel";
import "../workflowRun/workflowRun.css";
import { workflowsForItem } from "./workTransitionModel";
import { assigneeLabel } from "./workPeople";
import { isClosedItem, sourceName } from "./workItemClose";
import { ourStateLabel, ourStateTone } from "./workItemState";
import {
  FUTURE_SECTIONS, firstString, hasDetailValue, optionalSourceObject, rawFields, sourceRaw,
} from "./workItemDetailValues";
import {
  AutomationEligibility, DetailSection, FutureData, LifecycleSummary, MappingGrid, ObjectList,
} from "./WorkItemDetailParts";
import { WorkItemActivityTab, WorkItemDetailHeaderActions, WorkItemStartSection } from "./WorkItemDetailSections";
import { scrollToStartSection } from "./workItemStartSection";
import { useWorkItemDetailData, type WorkItemDetailData } from "./useWorkItemDetailData";
import { PullRequestList, RepositoryImpactMap } from "./WorkItemRepositoryParts";
import { SidePanel } from "../../layout/SidePanel";
import { StatusLabel } from "../../layout/StatusLabel";
import { AdvancedSection } from "../../layout/FormSection";
import type { ProjectOption } from "../../chatOptionTypes";

// The Work Item detail: the design system's side panel over the dimmed board or list, or the same content
// as a page. Tabs Overview | Activity | <source>; the header carries Open in <source>, Close item and Start workflow.
// Overview stays lean: state, priority, assignee, the request and the item's runs (if any); the start form (and the
// move to another state) appears only after "Start workflow". The source's fields only on its tab.

export type WorkItemDetailTab = "overview" | "activity" | "source";

type OverviewProps = {
  item: WorkItem;
  workflows: WorkWorkflowDefinition[];
  projects: ProjectOption[];
  focusPlanId: string | null;
  changePlanSection: ReactNode;
  startSection: ReactNode;
  acceptanceCriteria: string;
  data: WorkItemDetailData;
};

// Overview: state, priority, assignee, the request, tasks, runs, the plan and the delivery context.
function WorkItemOverview({ item, workflows, projects, focusPlanId, changePlanSection, startSection, acceptanceCriteria, data }: OverviewProps) {
  const serviceNow = isServiceNowItem(item);
  const capturedReviewers = optionalSourceObject(item, "reviewers");
  return (
      <>
        {focusPlanId ? changePlanSection : null}
        <div className="work-detail__status-strip" data-testid="work-detail-status">
          <StatusLabel label={ourStateLabel(item, workflows)} tone={ourStateTone(item)} testId="work-detail-state" />
          {item.priority ? <span>Priority {item.priority}</span> : null}
          <span data-testid="work-detail-assignee">{assigneeLabel(item)}</span>
          <ExceptionBadges exceptions={workItemExceptions(item)} />
          <a className="work-detail__source-link" href={`/chat?area=coding&work_item_id=${encodeURIComponent(item.id)}`}>
            Open in Coding Sessions
          </a>
        </div>
        {startSection}
        {serviceNow ? <WorkItemServiceNowSource item={item} projects={projects} part="request" />
          : <WorkItemJiraSource item={item} projects={projects} acceptanceCriteria={acceptanceCriteria} part="request" />}
        {item.task_list?.length ? (
          <DetailSection title={`Tasks · ${taskProgress(item.task_list)}`}>
            <div data-testid="work-detail-tasks"><TaskList items={item.task_list} /></div>
          </DetailSection>
        ) : null}
        <WorkItemRuns key={item.id} item={item} />
        {focusPlanId ? null : changePlanSection}
        <DetailSection title="Analysis">
          <WorkItemAnalysis key={item.id} item={item} />
        </DetailSection>
        {/* Repository impact and pull requests only once there is something to show (or a failed load). */}
        {data.changeUnits.length || data.changeUnitError ? (
          <DetailSection title="Repository Impact">
            {data.changeUnitError ? <p className="work-detail__empty">{data.changeUnitError}</p> : null}
            <RepositoryImpactMap changeUnits={data.changeUnits} pullRequests={data.pullRequests} />
          </DetailSection>
        ) : null}
        {data.pullRequests.length ? (
          <DetailSection title="Pull requests">
            <PullRequestList pullRequests={data.pullRequests} />
          </DetailSection>
        ) : null}
        <DetailSection title="Reviewer Recommendations">
          {hasDetailValue(capturedReviewers) ? <FutureData value={capturedReviewers} /> : null}
          <WorkReviewerRecommendations item={item} />
        </DetailSection>
        <AdvancedSection label="Automation and lifecycle" testId="work-detail-advanced">
          <DetailSection title="Octryx Automation">
            <AutomationEligibility item={item} />
          </DetailSection>
          <DetailSection title="Execution Lifecycle">
            {data.lifecycleError ? <p className="work-detail__empty">{data.lifecycleError}</p> : null}
            <LifecycleSummary lifecycle={data.lifecycle} item={item} />
          </DetailSection>
        </AdvancedSection>
      </>
  );
}

type SourceTabProps = { item: WorkItem; projects: ProjectOption[]; acceptanceCriteria: string; source: string };

function WorkItemSourceTab({ item, projects, acceptanceCriteria, source }: SourceTabProps) {
  const serviceNow = isServiceNowItem(item);
  const raw = sourceRaw(item);
  return (
      <>
        <div className="work-detail__status-strip" data-testid="work-detail-source-status">
          <span>{workItemDetailStatus(item)}</span>
        </div>
        {serviceNow ? <WorkItemServiceNowSource item={item} projects={projects} part="fields" />
          : <WorkItemJiraSource item={item} projects={projects} acceptanceCriteria={acceptanceCriteria} part="fields" />}
        <DetailSection title="Linked Issues">
          <ObjectList values={item.linked_issues || []} emptyText="No linked issues captured." />
        </DetailSection>
        <DetailSection title="Source Mapping">
          {/* The field ownership names internal fields (work_state, sync_state, pr_links): support detail, folded away
              with the raw evidence. */}
          <details className="work-detail__raw" data-testid="work-source-mapping-technical">
            <summary>Technical details</summary>
            <MappingGrid
              groups={[
                { title: `${source}-owned`, values: ["summary", "description", "status", "priority", "assignee", "fixVersion", "sprint"] },
                { title: "Octryx-owned", values: ["work_state", "sync_state", "change_plan", "execution_runs", "acceptance_state"] },
                { title: "Sync-back candidates", values: ["workflow_state", "comments", "pr_links", "validation_summary", "review_state"] },
              ]}
            />
            <h4>Raw {source} evidence</h4>
            <pre>{JSON.stringify(raw || {}, null, 2)}</pre>
          </details>
        </DetailSection>
        {FUTURE_SECTIONS.map((section) => (
          <DetailSection key={section.key} title={section.title}>
            <FutureData value={optionalSourceObject(item, section.key)} />
          </DetailSection>
        ))}
      </>
  );
}

function itemAcceptanceCriteria(item: WorkItem) {
  const fields = rawFields(item);
  return firstString(
    item.source_fields?.acceptance_criteria,
    fields.acceptanceCriteria,
    fields.customfield_acceptance_criteria,
  );
}

type WorkItemDetailPanelProps = {
  item: WorkItem;
  workflows: WorkWorkflowDefinition[];
  // Workspace names, and a reload after an applied transition.
  projects?: ProjectOption[];
  onItemChanged?: () => void;
  onClose: () => void;
  // The Change Plan opened from a plan list or link; it is shown and decided by this exact id.
  focusPlanId?: string | null;
  onSelectPlan?: (planId: string) => void;
  onPlansChanged?: () => void;
  mode?: "panel" | "page";
  pageHref?: string;
};

export function WorkItemDetailPanel({ item, workflows, onClose, focusPlanId = null, onSelectPlan, onPlansChanged,
  projects = [], onItemChanged, mode = "panel", pageHref }: WorkItemDetailPanelProps) {
  const [tab, setTab] = useState<WorkItemDetailTab>("overview");
  const [starting, setStarting] = useState(false);
  const canManage = useCanManageWork();
  const data = useWorkItemDetailData(item.id, setTab, setStarting);
  const acceptanceCriteria = itemAcceptanceCriteria(item);
  const source = sourceName(item);

  const changed = () => { data.setTimelineKey((value) => value + 1); onItemChanged?.(); };
  const startWorkflow = () => { setTab("overview"); setStarting(true); scrollToStartSection(); };
  const movable = workflowsForItem(item, workflows).length > 0;
  // A closed item starts no run; it can still be moved (e.g. reopened) when a workflow covers it.
  const closed = isClosedItem(item);
  const actionLabel = closed ? "Move item" : "Start workflow";

  // Mounted once: directly under the heading when a plan was chosen (from a plan list or a
  // `change_plan_id` link), otherwise in its usual place after the delivery context. Keyed by item
  // so a switch to another item never shows the previous item's plans.
  const changePlanSection = (
    <DetailSection title={focusPlanId ? "Selected Change Plan" : "Change Plan"}>
      <WorkChangePlans key={item.id} item={item} workflows={workflows} focusPlanId={focusPlanId}
        onSelectPlan={onSelectPlan} onPlansChanged={onPlansChanged} />
    </DetailSection>
  );
  const startSection = starting ? (
    <WorkItemStartSection item={item} workflows={workflows} actionLabel={actionLabel} closed={closed} movable={movable}
      onCancel={() => setStarting(false)} onApplied={changed} />
  ) : null;

  return (
    <SidePanel
      title={item.source_key}
      subtitle={item.title}
      onClose={onClose}
      mode={mode}
      pageHref={pageHref}
      headerActions={<WorkItemDetailHeaderActions item={item} onClosed={changed} showStart={!((closed && !movable) || !canManage)}
        closed={closed} starting={starting} actionLabel={actionLabel} onStart={startWorkflow} backButton={mode === "page"} onBack={onClose} />}
      testId="work-item-panel"
      tabs={detailTabs(tab, setTab, source)}
    >
      <div className="work-detail" aria-label="Work Item detail" data-testid="work-item-detail">
        {tab === "overview" ? (
          <WorkItemOverview item={item} workflows={workflows} projects={projects} focusPlanId={focusPlanId}
            changePlanSection={changePlanSection} startSection={startSection} acceptanceCriteria={acceptanceCriteria} data={data} />
        ) : tab === "activity" ? <WorkItemActivityTab item={item} workflows={workflows} timelineKey={data.timelineKey} />
          : <WorkItemSourceTab item={item} projects={projects} acceptanceCriteria={acceptanceCriteria} source={source} />}
      </div>
    </SidePanel>
  );
}

function detailTabs(tab: WorkItemDetailTab, setTab: (tab: WorkItemDetailTab) => void, source: string) {
  return {
    label: "Work item detail",
    idPrefix: "work-item-detail",
    value: tab,
    onChange: (key: string) => setTab(key as WorkItemDetailTab),
    tabs: [
      { key: "overview", label: "Overview" },
      { key: "activity", label: "Activity" },
      { key: "source", label: source },
    ],
  };
}
