import type { WebSearchOverview } from "../../admin/components/workspaceKnowledge/workspaceKnowledgeTypes";
import { providerDisplayName, providerSummary } from "./researchSourceRows";

// "confidential" → "Confidential" (a data class in words).
const classWords = (value: string) => value.charAt(0).toUpperCase() + value.slice(1).replace(/_/g, " ");

// The workspace's search mode and provider. The mode stays visible; the provider's name, check and diagnostics sit
// in a collapsed section whose summary carries the provider status. What the modes mean, the platform blocklist and
// the provider check are explained in the page help (help/knowledge/knowledgeResearch.md), not on the page.
// Changing the mode and checking the provider need the workspace author role; the server enforces it.
export function KnowledgeResearchPolicy({ overview, mayAuthor, busy, onMode, onCanary }: {
  overview: WebSearchOverview;
  mayAuthor: boolean;
  busy: boolean;
  onMode: (mode: WebSearchOverview["mode"]) => void;
  onCanary: () => void;
}) {
  const provider = overview.provider;
  const summary = providerSummary(provider);
  return (
    <div className="knowledge-research__policy">
      {mayAuthor ? (
        <div className="knowledge-contribution__inline" role="radiogroup" aria-label="Search mode">
          <label><input type="radio" name="knowledge-research-mode" checked={overview.mode === "open"} disabled={busy}
            onChange={() => onMode("open")} /> Open (blocked websites excluded)</label>
          <label><input type="radio" name="knowledge-research-mode" checked={overview.mode === "trusted_only"} disabled={busy}
            onChange={() => onMode("trusted_only")} /> Approved websites only</label>
        </div>
      ) : null}
      {!mayAuthor ? <p className="admin-panel__note" data-testid="research-mode">
        Search mode: {overview.mode === "trusted_only" ? "Approved websites only" : "Open (blocked websites excluded)"}</p> : null}
      {!provider.name ? <p className="admin-panel__note" role="status">No search provider is configured, so web search and research cannot search.</p> : null}
      <details className={`knowledge-research__provider${summary.attention ? " knowledge-research__provider--attention" : ""}`}>
        <summary>{summary.text}</summary>
        <div className="knowledge-research__provider-body">
          <div className="knowledge-contribution__inline">
            <span>Search provider: <strong>{providerDisplayName(provider.name) ?? "not configured"}</strong></span>
            <span className={`admin-panel__badge ${summary.badge}`}>{summary.stateLabel}</span>
            {provider.quarantine_reason ? <span className="admin-panel__cell--muted">{provider.quarantine_reason}</span> : null}
            {mayAuthor && provider.name ? <button type="button" className="admin-panel__action-btn" disabled={busy}
              onClick={onCanary}>Check provider</button> : null}
          </div>
          {provider.data_policy_class ? <p className="admin-panel__note">Queries may contain workspace data up to {classWords(provider.data_policy_class)}.</p> : null}
          <p className="admin-panel__note">Platform blocklist: {overview.blocklist_version}</p>
        </div>
      </details>
    </div>
  );
}
