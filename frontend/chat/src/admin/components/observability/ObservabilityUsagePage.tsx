import { useCallback, useEffect, useState } from "react";

import { useAdminNavigation } from "../../adminNavigation";
import type { ReadJsonFn } from "../../hooks/useAdminTabLoader.types";
import { Segmented, type ProjectOption } from "./obUi";
import { readErrorMessage } from "./obFormat";
import { SpendTrend } from "./SpendTrend";
import { rangeLabel, unpricedModels, USAGE_WINDOWS, type UsagePayload, type UsageWindow } from "./usageModel";
import {
  UsageBudgets, UsageByModel, UsageByUser, UsageByWorkspace, UsagePricingWarning, UsageTiles,
} from "./ObservabilityUsageParts";
import "./observability.css";

type Props = { projects: ProjectOption[]; readJson: ReadJsonFn };

// Observability → Usage & costs: spend from usage_events in a window, how much of it is priced, and budgets
// read-only. Prices are set in Runtime → Providers and caps in Runtime → Limits & budgets, never here.
export function ObservabilityUsagePage({ readJson }: Props) {
  const { openAdminTab } = useAdminNavigation();
  const [usageWindow, setUsageWindow] = useState<UsageWindow>("month");
  const [data, setData] = useState<UsagePayload | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setData(await readJson<UsagePayload>(`/api/v1/observability/usage?window=${usageWindow}`));
      setError(null);
    } catch (loadError) {
      setError(readErrorMessage(loadError, "Usage could not be loaded."));
    }
  }, [readJson, usageWindow]);

  useEffect(() => {
    void load();
  }, [load]);

  const tiles = data?.tiles;
  const missing = data ? unpricedModels(data.by_model) : [];

  return (
    <div className="ob-page" data-testid="observability-usage">
      <div className="ob-between">
        <Segmented label="Window" options={USAGE_WINDOWS} value={usageWindow} onChange={setUsageWindow} />
        <span className="ob-row">
          <span className="ob-muted">{data ? rangeLabel(data.since, data.until) : ""}</span>
          {/* Operations › Costs: the same money per run, work item and person, next to what it delivered. */}
          <button type="button" className="ob-link" data-testid="usage-costs-link" onClick={() => openAdminTab("operationsCosts")}>
            Costs per run and outcome
          </button>
        </span>
      </div>
      {error ? <div className="ob-warn" role="alert">{error}</div> : null}
      {data && missing.length ? <UsagePricingWarning data={data} openAdminTab={openAdminTab} /> : null}
      {tiles ? <UsageTiles tiles={tiles} /> : null}
      {data ? <SpendTrend days={data.daily} /> : null}
      {data ? (
        <>
          <div className="ob-two">
            <UsageByModel data={data} openAdminTab={openAdminTab} />
            <UsageByWorkspace data={data} />
          </div>
          <div className="ob-two">
            <UsageByUser data={data} />
            <UsageBudgets data={data} openAdminTab={openAdminTab} />
          </div>
        </>
      ) : null}
    </div>
  );
}
