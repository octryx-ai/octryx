// The chat statistics panel's optional sections: workflow ROI, code intelligence and the session's pull requests.
import type { SessionPullRequest, ThreadCodeIntelligenceStats, ThreadUsageStats } from "../chatUsageTypes";
import { formatCost, formatPercent, formatSignedPercent, formatSignedTokenCount, formatTokenCount } from "./statsFormat";

export function workflowRoiSection(workflowRoi: NonNullable<ThreadUsageStats["workflowRoi"]>) {
  return (
    <div className="stats-panel__section">
      <div className="stats-panel__section-title">Workflow ROI</div>
      <div className="stats-panel__grid">
        <div className="stats-panel__card">
          <span className="stats-panel__value">
            {formatSignedPercent(
              workflowRoi.savings.tokenReductionPercent,
            )}
          </span>
          <span className="stats-panel__label">Token delta</span>
        </div>
        <div className="stats-panel__card">
          <span className="stats-panel__value">
            {formatSignedPercent(workflowRoi.savings.costReductionPercent)}
          </span>
          <span className="stats-panel__label">Cost delta</span>
        </div>
      </div>
      <div className="stats-panel__rows">
        <div className="stats-panel__row stats-panel__row--stacked">
          <span>Workflow</span>
          <strong>
            {workflowRoi.workflowId ||
              workflowRoi.workflowClass ||
              "Unknown workflow"}
          </strong>
        </div>
        <div className="stats-panel__row">
          <span>Baseline sessions</span>
          <strong>
            {formatTokenCount(workflowRoi.baselineSampleCount)}
          </strong>
        </div>
        <div className="stats-panel__row">
          <span>Token savings</span>
          <strong>
            {formatSignedTokenCount(workflowRoi.savings.tokenDelta)}
          </strong>
        </div>
        <div className="stats-panel__row">
          <span>Cost savings</span>
          <strong>{formatCost(workflowRoi.savings.costDelta)}</strong>
        </div>
        <div className="stats-panel__row">
          <span>LLM requests</span>
          <strong>
            {formatSignedTokenCount(workflowRoi.savings.llmRequestDelta)}
          </strong>
        </div>
        <div className="stats-panel__row">
          <span>Tool calls</span>
          <strong>
            {formatSignedTokenCount(workflowRoi.savings.toolCallDelta)}
          </strong>
        </div>
        <div className="stats-panel__row stats-panel__row--stacked">
          <span>Quality gates</span>
          <strong>
            {workflowRoi.quality.status === "measured"
              ? `${formatPercent(workflowRoi.quality.current.passRate)} current · ${formatPercent(
                  workflowRoi.quality.baseline.passRate,
                )} baseline`
              : "Not measured"}
          </strong>
        </div>
        {workflowRoi.status === "insufficient_baseline" ? (
          <div className="stats-panel__row stats-panel__row--stacked">
            <span>ROI status</span>
            <strong>No comparable baseline sessions yet.</strong>
          </div>
        ) : null}
      </div>
    </div>
  );
}

export function codeIntelligenceSection(codeIntelligence: ThreadCodeIntelligenceStats) {
  return (
    <div className="stats-panel__section">
      <div className="stats-panel__section-title">Code intelligence</div>
      <div className="stats-panel__grid">
        <div className="stats-panel__card">
          <span className="stats-panel__value">
            {formatTokenCount(codeIntelligence.codeToolCalls)}
          </span>
          <span className="stats-panel__label">Code tools</span>
        </div>
        <div className="stats-panel__card">
          <span className="stats-panel__value">
            {formatPercent(codeIntelligence.fallbackRate)}
          </span>
          <span className="stats-panel__label">Fallback rate</span>
        </div>
      </div>
      <div className="stats-panel__rows">
        <div className="stats-panel__row">
          <span>Tool calls</span>
          <strong>
            {formatTokenCount(codeIntelligence.totalToolCalls)}
          </strong>
        </div>
        <div className="stats-panel__row">
          <span>Fallback calls</span>
          <strong>
            {formatTokenCount(codeIntelligence.fallbackToolCalls)}
          </strong>
        </div>
        {codeIntelligence.repositoryBackends &&
        Object.keys(codeIntelligence.repositoryBackends).length ? (
          <div className="stats-panel__row stats-panel__row--stacked">
            <span>Effective repo backends</span>
            <strong>
              {Object.entries(codeIntelligence.repositoryBackends)
                .map(([key, value]) => `${key}: ${value}`)
                .join(" · ")}
            </strong>
          </div>
        ) : null}
        {codeIntelligence.rows.map((row) => (
          <div
            key={row.label}
            className="stats-panel__row stats-panel__row--stacked"
          >
            <span>{row.label}</span>
            <strong>{row.value}</strong>
          </div>
        ))}
      </div>
    </div>
  );
}

export function pullRequestsSection(pullRequests: SessionPullRequest[]) {
  if (!pullRequests.length) return null;
  return (
    <div className="stats-panel__section" data-testid="session-pull-requests">
      <div className="stats-panel__section-title">Pull requests</div>
      <div className="stats-panel__rows">
        {pullRequests.map((pullRequest) => (
          <div key={pullRequest.url} className="stats-panel__row stats-panel__row--stacked">
            <a href={pullRequest.url} target="_blank" rel="noopener noreferrer">
              {pullRequest.title || pullRequest.url}
            </a>
            <strong>{pullRequest.state || "unknown"}</strong>
          </div>
        ))}
      </div>
    </div>
  );
}
