// State of the Coding page and its reads: the session list, the selected session's detail and the review verdicts.

import { useEffect, useRef, useState, type Dispatch, type MutableRefObject, type SetStateAction } from "react";
import { loadCodingWorkspaceData } from "./codingApi";
import { codingNavFromSearch, type CodingNavKey } from "./CodingAreaNav";
import type { CodingExecutionNoticeData } from "./codingExecutionNoticeModel";
import type { CodingQueueKey } from "./codingQueuePresenter";
import type { CodingReviewSummary, CodingSessionDetailData, CodingSessionSummary, CodingSessionTab } from "./codingTypes";
import { addressSelectionAfterRead } from "./codingSelectionAddress";
import type { WorkItem } from "../work/workItemTypes";
import type { WorkRepositoryProfile } from "../work/workCodingPipelineTypes";
import { readSidebarCollapsedPreference, replaceCodingWorkItemUrl, selectedWorkItemIdFromUrl } from "./codingAreaBrowser";
import {
  loadSessionDetail,
  refreshReviewOf,
  sessionsFromCandidates,
  type CodingReadRefs,
  type ReviewAudit,
  type SessionInputs,
} from "./codingAreaReads";

// The selection after a Workspace read: the asked-for session if it is still there, else the first session.
function nextSelection(
  current: string | null,
  preferredSelectedId: string | undefined,
  items: WorkItem[],
  nextSessions: CodingSessionSummary[],
) {
    const requestedId = preferredSelectedId || current;
    const requestedWorkItemExists = requestedId ? items.some((item) => item.id === requestedId) : false;
    const nextSelectedId = nextSessions.some((session) => session.id === requestedId)
      ? requestedId
      : requestedWorkItemExists
        ? requestedId
        : nextSessions[0]?.id || null;
    // The first session picked here landed in the address as `work_item_id` unasked,
    // on every page. The address keeps only a session that was asked for (by the address or the caller, e.g. a
    // session just started); a picked one is shown, not written, and an asked-for one that is gone leaves.
    replaceCodingWorkItemUrl(addressSelectionAfterRead({
      asked: preferredSelectedId || selectedWorkItemIdFromUrl(), shown: nextSelectedId }));
    return nextSelectedId;
}

type WorkspaceReadSetters = {
  setLoading: Dispatch<SetStateAction<boolean>>;
  setError: Dispatch<SetStateAction<string | null>>;
  setWorkItems: Dispatch<SetStateAction<WorkItem[]>>;
  setRepositoryProfiles: Dispatch<SetStateAction<WorkRepositoryProfile[]>>;
  setWorkItemCount: Dispatch<SetStateAction<number>>;
  setSessions: Dispatch<SetStateAction<CodingSessionSummary[]>>;
  setSelectedId: Dispatch<SetStateAction<string | null>>;
};

async function loadWorkspaceSessions(
  refs: CodingReadRefs & { workspaceLoads: MutableRefObject<number> },
  workspaceId: string,
  setters: WorkspaceReadSetters,
  preferredSelectedId?: string,
) {
  const { reviewReads, workspaceLoads } = refs;
  const { setLoading, setError, setWorkItems, setRepositoryProfiles, setWorkItemCount, setSessions, setSelectedId } = setters;
  setLoading(true);
  setError(null);
  const started = ++reviewReads.current;
  const load = ++workspaceLoads.current;
  try {
    const { items, sessionCandidates, repositoryProfiles: nextRepositoryProfiles } = await loadCodingWorkspaceData(workspaceId);
    // A Workspace switch while this read ran: the newer read owns the list.
    if (load !== workspaceLoads.current) return;
    setWorkItems(items);
    setRepositoryProfiles(nextRepositoryProfiles);
    setWorkItemCount(items.length);
    const nextSessions = sessionsFromCandidates(refs, sessionCandidates, started);
    setSessions(nextSessions);
    setSelectedId((current) => nextSelection(current, preferredSelectedId, items, nextSessions));
  } catch (err) {
    if (load === workspaceLoads.current) setError(err instanceof Error ? err.message : "Failed to load Coding Sessions");
  } finally {
    if (load === workspaceLoads.current) setLoading(false);
  }
}

// Side panels and preferences of the page that no read touches.
function useCodingPanelState() {
  const [sidebarCollapsed, setSidebarCollapsed] = useState(readSidebarCollapsedPreference);
  const [startDialogOpen, setStartDialogOpen] = useState(false);
  const [agentStartBusy, setAgentStartBusy] = useState(false);
  const [executionNotice, setExecutionNotice] = useState<CodingExecutionNoticeData | null>(null);
  // Coding rules: whether this person may add a rule (the page's primary action), and its side panel.
  const [rulesEditable, setRulesEditable] = useState(false);
  const [addingRule, setAddingRule] = useState(false);
  return {
    sidebarCollapsed, setSidebarCollapsed, startDialogOpen, setStartDialogOpen, agentStartBusy, setAgentStartBusy,
    executionNotice, setExecutionNotice, rulesEditable, setRulesEditable, addingRule, setAddingRule,
  };
}

export function useCodingAreaState(workspaceId: string) {
  const [sessionQueue, setSessionQueue] = useState<CodingQueueKey>("sessions");
  const [sessions, setSessions] = useState<CodingSessionSummary[]>([]);
  const [workItems, setWorkItems] = useState<WorkItem[]>([]);
  const [repositoryProfiles, setRepositoryProfiles] = useState<WorkRepositoryProfile[]>([]);
  const [workItemCount, setWorkItemCount] = useState(0);
  const [loading, setLoading] = useState(true);
  const [detailLoading, setDetailLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // `coding_view=<page>` opens a Coding page directly (help links); anything else opens Sessions.
  const [activeNav, setActiveNav] = useState<CodingNavKey>(() => codingNavFromSearch(window.location.search));
  const [activeTab, setActiveTab] = useState<CodingSessionTab>("overview");
  const [search, setSearch] = useState("");
  const [selectedId, setSelectedId] = useState<string | null>(() => selectedWorkItemIdFromUrl());
  const [detail, setDetail] = useState<CodingSessionDetailData | null>(null);
  const [detailReload, setDetailReload] = useState(0);
  const panels = useCodingPanelState();
  // The reviewer verdict. The audit report shown for the selected item lives here, apart
  // from the rest of the detail, so a newer read is never replaced by an older one (see acceptRead).
  const [reviewAudit, setReviewAudit] = useState<ReviewAudit>(null);
  const [pinnedDetail, setPinnedDetail] = useState<{ queue: string; id: string } | null>(null);
  const sessionInputs = useRef(new Map<string, SessionInputs>());
  const reviewReads = useRef(0);
  const workspaceLoads = useRef(0);
  const reviewFloors = useRef(new Map<string, number>());
  // The verdict each item shows now, also when its session row is not built yet.
  const shownReviews = useRef(new Map<string, CodingReviewSummary>());
  const refs = { sessionInputs, reviewReads, reviewFloors, shownReviews };

  const refreshReview = (itemId: string) => refreshReviewOf(refs, setSessions, setReviewAudit, itemId);
  const refresh = (preferredSelectedId?: string) => loadWorkspaceSessions({ ...refs, workspaceLoads }, workspaceId, {
    setLoading, setError, setWorkItems, setRepositoryProfiles, setWorkItemCount, setSessions, setSelectedId,
  }, preferredSelectedId);

  useEffect(() => {
    void refresh();
    // The list belongs to the selected Workspace: switching it reloads.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [workspaceId]);

  useEffect(() => {
    if (!selectedId) {
      setDetail(null);
      return;
    }
    return loadSessionDetail({ sessionInputs, reviewReads, reviewFloors, shownReviews }, selectedId, {
      setDetail, setDetailLoading, setReviewAudit, setSessions, setError,
    });
  }, [selectedId, detailReload]);

  return {
    sessionQueue, setSessionQueue, sessions, workItems, repositoryProfiles, workItemCount, loading, detailLoading,
    error, setError, activeNav, setActiveNav, activeTab, setActiveTab, search, setSearch, selectedId, setSelectedId,
    detail, setDetailReload, ...panels, reviewAudit, pinnedDetail, setPinnedDetail, refresh, refreshReview,
  };
}
