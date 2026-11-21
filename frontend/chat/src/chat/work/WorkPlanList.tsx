import { useEffect, useRef, useState, type Dispatch, type MutableRefObject, type SetStateAction } from "react";

import { Badge } from "./WorkAreaViews";
import { loadChangePlanSummaries } from "./workPlanListApi";
import { DEFAULT_PLAN_LIST_FILTER, errorMessage, planListEmptyState, planListQuery, planStatusChips, planTotal, reviewDemandText, type WorkPlanListFilter, type WorkPlanListMode } from "./workPlanListModel";
import { planStatusLabel } from "./planStatus";
import type { WorkChangePlanList, WorkChangePlanListQuery, WorkChangePlanSummary } from "./workPlanListTypes";
import { formatDateTime } from "./workUtils";
import "./workPlanList.css";
import { LoadingState } from "../../layout/LoadingState";

type WorkPlanListProps = {
  mode: WorkPlanListMode;
  projectId?: string;
  // Changes on Refresh and after a plan decision or new version; the list then reloads in place.
  reloadKey: string | number;
  selectedPlanId: string | null;
  onOpenPlan: (plan: WorkChangePlanSummary) => void;
  onOpenWorkItems?: () => void;
  load?: (query: WorkChangePlanListQuery) => Promise<WorkChangePlanList>;
};

type PlanPageSetters = {
  setRows: Dispatch<SetStateAction<WorkChangePlanSummary[]>>;
  setCursor: Dispatch<SetStateAction<string | null>>;
  setLoadingMore: Dispatch<SetStateAction<boolean>>;
  setError: Dispatch<SetStateAction<string | null>>;
};

// The next page joins the rows without repeating one; a newer first-page request wins.
async function loadMorePlans(
  { mode, projectId = "", load = loadChangePlanSummaries }: WorkPlanListProps,
  filter: WorkPlanListFilter,
  cursor: string,
  request: MutableRefObject<number>,
  { setRows, setCursor, setLoadingMore, setError }: PlanPageSetters,
) {
  const current = request.current;
  setLoadingMore(true);
  try {
    const next = planListQuery(mode, filter, cursor);
    const page = await load(projectId ? { ...next, projectId } : next);
    if (current !== request.current) return;
    setRows((existing) => {
      const seen = new Set(existing.map((row) => row.id));
      return [...existing, ...page.items.filter((row) => !seen.has(row.id))];
    });
    setCursor(page.next_cursor);
  } catch (err) {
    if (current === request.current) setError(errorMessage(err, "More Change Plans could not be loaded."));
  } finally {
    setLoadingMore(false);
  }
}

function useWorkPlanRows(props: WorkPlanListProps, filter: WorkPlanListFilter) {
  const { mode, projectId = "", reloadKey, load = loadChangePlanSummaries } = props;
  const [rows, setRows] = useState<WorkChangePlanSummary[]>([]);
  const [counts, setCounts] = useState<Record<string, number>>({});
  const [cursor, setCursor] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const request = useRef(0);
  const shownQuery = useRef("");

  useEffect(() => {
    const current = ++request.current;
    const base = planListQuery(mode, filter);
    const query = projectId ? { ...base, projectId } : base;
    const queryKey = JSON.stringify(query);
    // A reload of the same query keeps the rows on screen until the fresh page arrives; a new
    // view or filter starts from the loading state.
    if (queryKey !== shownQuery.current) setLoading(true);
    shownQuery.current = queryKey;
    setError(null);
    load(query)
      .then((page) => {
        if (current !== request.current) return;
        setRows(page.items);
        setCounts(page.status_counts);
        setCursor(page.next_cursor);
      })
      .catch((err: unknown) => {
        if (current !== request.current) return;
        setRows([]);
        setCursor(null);
        setError(errorMessage(err, "Change Plans could not be loaded."));
      })
      .finally(() => {
        if (current === request.current) setLoading(false);
      });
  }, [mode, filter, projectId, reloadKey, load]);

  async function loadMore() {
    if (!cursor || loadingMore) return;
    await loadMorePlans(props, filter, cursor, request, { setRows, setCursor, setLoadingMore, setError });
  }

  return { rows, counts, cursor, loading, loadingMore, error, loadMore };
}

// Change Plans and Plan reviews: a list of real plans, loaded on its own so it never waits
// for the Work Item, workflow or configuration loads of the rest of the Work area.
export function WorkPlanList(props: WorkPlanListProps) {
  const { mode, selectedPlanId, onOpenPlan, onOpenWorkItems } = props;
  const [filter, setFilter] = useState<WorkPlanListFilter>(DEFAULT_PLAN_LIST_FILTER);
  const { rows, counts, cursor, loading, loadingMore, error, loadMore } = useWorkPlanRows(props, filter);

  const chooseStatus = (status: string) => setFilter((current) => ({ ...current, status }));
  const toggleSuperseded = () =>
    setFilter((current) => ({
      showSuperseded: !current.showSuperseded,
      status: current.showSuperseded && current.status === "superseded" ? "" : current.status,
    }));

  const empty = planListEmptyState(mode, filter);
  // No status filters while there is nothing to filter.
  const nothingYet = !loading && !error && planTotal(counts) === 0 && filter.status === "" && !filter.showSuperseded;

  return (
    <div className="work-plan-list">
      {mode === "reviews" ? (
        <p className="work-plan-list__summary" data-testid="plan-review-demand">
          {loading || error ? "" : reviewDemandText(counts)}
        </p>
      ) : nothingYet ? null : (
        <WorkPlanStatusFilter counts={counts} filter={filter} chooseStatus={chooseStatus}
          toggleSuperseded={toggleSuperseded} />
      )}

      {error ? <div className="work-area__error" role="alert">{error}</div> : null}
      {loading ? <LoadingState label="plans" /> : null}

      {!loading && !error && rows.length === 0 ? (
        <div className="work-empty">
          <div className="work-empty__eyebrow">{mode === "reviews" ? "Waiting for review" : "Plans"}</div>
          <h2>{empty.title}</h2>
          <p>{empty.body}</p>
          {empty.openWorkItems && onOpenWorkItems ? (
            <button type="button" className="work-area__button work-area__button--primary" onClick={onOpenWorkItems}>
              Open work items
            </button>
          ) : null}
        </div>
      ) : null}

      {!loading && rows.length > 0 ? (
        <WorkPlanTable rows={rows} selectedPlanId={selectedPlanId} onOpenPlan={onOpenPlan} />
      ) : null}

      {!loading && cursor ? (
        <button type="button" className="work-area__button work-plan-list__more" disabled={loadingMore}
          onClick={() => void loadMore()}>
          {loadingMore ? "Loading…" : "Load more"}
        </button>
      ) : null}
    </div>
  );
}

function WorkPlanStatusFilter({ counts, filter, chooseStatus, toggleSuperseded }: {
  counts: Record<string, number>;
  filter: WorkPlanListFilter;
  chooseStatus: (status: string) => void;
  toggleSuperseded: () => void;
}) {
  return (
    <div className="work-plan-list__toolbar" role="group" aria-label="Filter Change Plans by status">
      <button type="button" className={`work-area__button ${filter.status === "" ? "is-active" : ""}`}
        aria-pressed={filter.status === ""} onClick={() => chooseStatus("")}>
        All · {planTotal(counts)}
      </button>
      {planStatusChips(counts).map((chip) => (
        <button key={chip.status} type="button"
          className={`work-area__button ${filter.status === chip.status ? "is-active" : ""}`}
          aria-pressed={filter.status === chip.status} onClick={() => chooseStatus(chip.status)}>
          {chip.label} · {chip.count}
        </button>
      ))}
      <label className="work-plan-list__history">
        <input type="checkbox" checked={filter.showSuperseded} onChange={toggleSuperseded} />
        <span>Show superseded versions</span>
      </label>
    </div>
  );
}

function WorkPlanTable({ rows, selectedPlanId, onOpenPlan }: Pick<WorkPlanListProps, "selectedPlanId" | "onOpenPlan"> & {
  rows: WorkChangePlanSummary[];
}) {
  return (
    <div className="work-table-wrap">
      <table className="work-table work-plan-list__table">
        <thead>
          <tr>
            <th>Work item</th>
            <th>Plan</th>
            <th>Status</th>
            <th>Type</th>
            <th>Created by</th>
            <th>Updated</th>
            <th>Decided</th>
            <th>Detail</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.id} className={row.id === selectedPlanId ? "is-selected" : undefined}
              aria-selected={row.id === selectedPlanId}>
              <td>
                <strong>{row.work_item.source_key}</strong>
                <span>{row.work_item.title}</span>
              </td>
              <td>
                <strong>v{row.version}</strong>
                <span className="work-plan-list__plan-title">{row.title}</span>
              </td>
              <td>
                <Badge value={row.status} />
                {row.open_questions_count > 0 ? (
                  <span className="work-plan-list__meta">
                    {row.open_questions_count} open question{row.open_questions_count === 1 ? "" : "s"}
                  </span>
                ) : null}
              </td>
              <td>{row.plan_type ? row.plan_type.replaceAll("_", " ") : "Not recorded"}</td>
              <td>{row.created_by_name || "Unknown user"}</td>
              <td>{formatDateTime(row.updated_at || row.created_at)}</td>
              <td>{row.decided_at ? formatDateTime(row.decided_at) : "Not decided"}</td>
              <td>
                <button type="button" className="work-table__detail" onClick={() => onOpenPlan(row)}
                  aria-label={`Open ${row.work_item.source_key} plan version ${row.version}, ${planStatusLabel(row.status)}`}>
                  Open
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
