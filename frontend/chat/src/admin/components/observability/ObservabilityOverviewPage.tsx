import { useCallback, useEffect, useState } from "react";

import { useAdminNavigation } from "../../adminNavigation";
import type { ReadJsonFn } from "../../hooks/useAdminTabLoader.types";
import { HEALTH_BADGES, type HealthLink } from "./healthModel";
import { formatMoney, formatTime, readErrorMessage } from "./obFormat";
import { EmptyLine } from "../../../layout/EmptyLine";
import { Badge, type ProjectOption } from "./obUi";
import { attentionBreakdown, decisionsBreakdown, type OverviewPayload } from "./overviewModel";
import "./observability.css";

type Props = { projects: ProjectOption[]; readJson: ReadJsonFn };

// Observability → Overview: needs attention, health strip, spend this month, decisions today. Every item
// links to the screen that owns it; nothing is decided here.
export function ObservabilityOverviewPage({ readJson }: Props) {
  const { openAdminTab } = useAdminNavigation();
  const [data, setData] = useState<OverviewPayload | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setData(await readJson<OverviewPayload>("/api/v1/observability/overview"));
      setError(null);
    } catch (loadError) {
      setError(readErrorMessage(loadError, "The overview could not be loaded."));
    } finally {
      setLoading(false);
    }
  }, [readJson]);

  useEffect(() => {
    void load();
  }, [load]);

  const open = (link: HealthLink) => {
    if (link?.tab) openAdminTab(link.tab);
    else if (link?.href) window.location.assign(link.href);
  };
  const summary = data?.health.summary;
  const month = data ? new Date(data.spend.since).toLocaleDateString("en-GB", { month: "long", timeZone: "UTC" }) : "";

  return (
    <div className="ob-page" data-testid="observability-overview">
      <div className="ob-between">
        <span className="ob-muted">{data ? `Checked ${formatTime(data.checked_at)}` : ""}</span>
        <button type="button" className="admin-panel__action-btn" disabled={loading} onClick={() => void load()}>Refresh</button>
      </div>
      {error ? <div className="ob-warn" role="alert">{error}</div> : null}
      {data && summary ? <OverviewTiles data={data} summary={summary} month={month} openAdminTab={openAdminTab} /> : null}
      {data ? <AttentionCard data={data} onOpen={open} /> : null}
      {data ? <HealthStripCard data={data} openAdminTab={openAdminTab} /> : null}
    </div>
  );
}

type OpenTab = ReturnType<typeof useAdminNavigation>["openAdminTab"];

function OverviewTiles({ data, summary, month, openAdminTab }: {
  data: OverviewPayload;
  summary: OverviewPayload["health"]["summary"];
  month: string;
  openAdminTab: OpenTab;
}) {
  return (
    <div className="ob-tiles">
      <button type="button" className="ob-tile" onClick={() => document.getElementById("overview-attention")?.scrollIntoView({ behavior: "smooth" })}>
        <b>Needs attention</b><strong>{data.attention.length}</strong><span>{attentionBreakdown(data.attention)}</span>
      </button>
      <button type="button" className="ob-tile" onClick={() => openAdminTab("observabilityHealth")}>
        <b>Health</b>
        <strong>
          {summary.failing ? <Badge tone="danger">✕ {summary.failing} failing</Badge>
            : summary.degraded ? <Badge tone="attention">! {summary.degraded} degraded</Badge>
              : <Badge tone="active">✓ OK</Badge>}
        </strong>
        <span>{summary.degraded} degraded · {summary.unknown} unknown · {summary.ok} ok</span>
      </button>
      <button type="button" className="ob-tile" onClick={() => openAdminTab("usage")}>
        <b>Spend · {month}</b><strong>{formatMoney(data.spend.month_spend)}</strong>
        <span>
          {data.spend.priced_coverage !== null && data.spend.priced_coverage < 1
            ? `${Math.round((1 - data.spend.priced_coverage) * 100)} % of tokens unpriced → the real figure is higher`
            : "all platform-billed tokens are priced"}
        </span>
      </button>
      <button type="button" className="ob-tile" onClick={() => openAdminTab("observabilityDecisions")}>
        <b>Decisions · today</b><strong>{data.decisions_today.total}</strong>
        <span>{decisionsBreakdown(data.decisions_today.by_outcome)}</span>
      </button>
    </div>
  );
}

function AttentionCard({ data, onOpen }: { data: OverviewPayload; onOpen: (link: HealthLink) => void }) {
  return (
    <div className="admin-panel__card" id="overview-attention">
      <div className="admin-panel__section-header">
        <span>Needs attention</span>
        <span className="ob-muted">Each item opens the page where it is fixed.</span>
      </div>
      {data.attention.length ? (
        <div className="ob-list">
          {data.attention.map((item, index) => (
            <div className="ob-item" key={`${item.title}-${index}`}>
              <span><Badge tone={item.severity}>{item.label}</Badge><div className="ob-sub">{item.age}</div></span>
              <div><div className="ob-name">{item.title}</div><p>{item.cause}</p></div>
              <button type="button" className="admin-panel__action-btn" onClick={() => onOpen(item.link)}>{item.action} →</button>
            </div>
          ))}
        </div>
      ) : (
        <EmptyLine text={`Nothing needs attention. Last checked ${formatTime(data.checked_at)}.`} />
      )}
    </div>
  );
}

function HealthStripCard({ data, openAdminTab }: { data: OverviewPayload; openAdminTab: OpenTab }) {
  return (
    <div className="admin-panel__card">
      <div className="admin-panel__section-header">
        <span>Health at a glance</span>
        <button type="button" className="ob-link" onClick={() => openAdminTab("observabilityHealth")}>Open Health</button>
      </div>
      <div className="ob-strip">
        {data.health.strip.map((entry) => (
          <button type="button" key={entry.key} onClick={() => openAdminTab("observabilityHealth")}>
            <b>{entry.label}</b>
            <Badge tone={HEALTH_BADGES[entry.status][0]}>
              {entry.status === "ok" || !entry.counts[entry.status]
                ? HEALTH_BADGES[entry.status][1]
                : `${HEALTH_BADGES[entry.status][1].split(" ")[0]} ${entry.counts[entry.status]} ${entry.status}`}
            </Badge>
            {/* The server sends "–" when it has nothing to add; a lone dash is not shown. */}
            {entry.detail && entry.detail.trim() !== "–" ? <span className="ob-muted">{entry.detail}</span> : null}
          </button>
        ))}
      </div>
    </div>
  );
}
