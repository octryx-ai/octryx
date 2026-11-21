import { useCallback, useEffect, useState } from "react";
import type { FormEvent } from "react";
import { KnowledgeCitation } from "./KnowledgeCitation";
import { workspaceKnowledgeApi } from "./workspaceKnowledgeApi";
import type { ChangesResult, GraphStatus } from "./workspaceKnowledgeTypes";

const STATE_TEXT: Record<string, string> = {
  not_extracted: "The sources of this range were never extracted into the graph. Start the extraction below.",
  no_sources: "The workspace has no sources of this product in this version range.",
};

/** One request of the panel: busy while it runs, its error shown, a success clears the error. */
async function busyCall(setBusy: (busy: boolean) => void, setError: (error: string | null) => void, task: () => Promise<void>) {
  setBusy(true);
  try {
    await task();
    setError(null);
  } catch (err) {
    setError(err instanceof Error ? err.message : String(err));
  } finally {
    setBusy(false);
  }
}

// "What changed from X to Y": typed, cited facts from the knowledge graph.
export function KnowledgeChangesPanel({ workspaceId }: { workspaceId: string }) {
  const [product, setProduct] = useState("spring-boot");
  const [fromVersion, setFromVersion] = useState("3.5");
  const [toVersion, setToVersion] = useState("4.0");
  const [query, setQuery] = useState("");
  const [changesOnly, setChangesOnly] = useState(true);
  const [result, setResult] = useState<ChangesResult | null>(null);
  const [status, setStatus] = useState<GraphStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const loadStatus = useCallback(async () => {
    try {
      setStatus(await workspaceKnowledgeApi.graphStatus(workspaceId));
    } catch {
      setStatus(null);
    }
  }, [workspaceId]);

  useEffect(() => {
    void loadStatus();
  }, [loadStatus]);

  const run = async (event: FormEvent) => {
    event.preventDefault();
    await busyCall(setBusy, setError, async () => {
      setResult(
        await workspaceKnowledgeApi.changes(workspaceId, {
          product: product.trim(),
          from_version: fromVersion.trim() || null,
          to_version: toVersion.trim(),
          query: query.trim() || null,
          limit: 100,
          changes_only: changesOnly,
        }),
      );
    });
  };

  const extract = () => busyCall(setBusy, setError, async () => {
    setStatus(await workspaceKnowledgeApi.extractGraph(workspaceId, product.trim(), toVersion.trim()));
  });

  return (
    <div>
      <ChangesForm fields={{ product, fromVersion, toVersion, query, changesOnly }} busy={busy}
        setters={{ setProduct, setFromVersion, setToVersion, setQuery, setChangesOnly }} onRun={(event) => void run(event)} />

      <GraphStatusSection status={status} product={product} toVersion={toVersion} busy={busy}
        onExtract={() => void extract()} onRefresh={() => void loadStatus()} />

      {error ? <div className="admin-panel__hint" role="alert">{error}</div> : null}
      <ChangesResultView result={result} />
    </div>
  );
}

type ChangesFields = { product: string; fromVersion: string; toVersion: string; query: string; changesOnly: boolean };
type ChangesSetters = {
  setProduct: (value: string) => void;
  setFromVersion: (value: string) => void;
  setToVersion: (value: string) => void;
  setQuery: (value: string) => void;
  setChangesOnly: (value: boolean) => void;
};

function ChangesForm({ fields, busy, setters, onRun }: {
  fields: ChangesFields; busy: boolean; setters: ChangesSetters; onRun: (event: FormEvent) => void;
}) {
  return (
    <form className="user-edit-panel__section" onSubmit={onRun}>
      <div className="user-edit-panel__section-label">What changed between two versions</div>
      <div style={{ display: "grid", gridTemplateColumns: "minmax(0, 1fr) minmax(0, 0.6fr) minmax(0, 0.6fr) minmax(0, 1.4fr) auto", gap: "0.4rem" }}>
        <input className="admin-panel__input" placeholder="Product" value={fields.product}
          onChange={(event) => setters.setProduct(event.target.value)} />
        <input className="admin-panel__input" placeholder="From" value={fields.fromVersion}
          onChange={(event) => setters.setFromVersion(event.target.value)} />
        <input className="admin-panel__input" placeholder="To" value={fields.toVersion}
          onChange={(event) => setters.setToVersion(event.target.value)} />
        <input className="admin-panel__input" placeholder="Topic (optional, e.g. Jackson)" value={fields.query}
          onChange={(event) => setters.setQuery(event.target.value)} />
        <button type="submit" className="admin-panel__action-btn admin-panel__action-btn--primary" disabled={busy}>
          Show changes
        </button>
      </div>
      <label className="admin-panel__hint" style={{ display: "block", marginTop: "0.4rem" }}>
        <input type="checkbox" checked={fields.changesOnly} onChange={(event) => setters.setChangesOnly(event.target.checked)} />{" "}
        Only typed change records (removed, renamed, replaced, deprecated, requires, moved, default changed, new)
      </label>
    </form>
  );
}

function GraphStatusSection({ status, product, toVersion, busy, onExtract, onRefresh }: {
  status: GraphStatus | null; product: string; toVersion: string; busy: boolean; onExtract: () => void; onRefresh: () => void;
}) {
  return (
    <div className="user-edit-panel__section">
      <div className="user-edit-panel__section-label">Knowledge graph</div>
      <div className="admin-panel__hint">
        {status
          ? `${status.episodes} extracted sections · ${status.pending_revisions} revisions still being extracted`
          : "Graph status unavailable."}{" "}
        Extraction runs governed model calls for every section of the product version, in the background.
      </div>
      <button type="button" className="admin-panel__action-btn" onClick={onExtract} disabled={busy}>
        Extract {product || "product"} {toVersion} into the graph
      </button>{" "}
      <button type="button" className="admin-panel__action-btn" style={{ marginLeft: "0.4rem" }}
        onClick={onRefresh}>
        Refresh
      </button>
    </div>
  );
}

function ChangesResultView({ result }: { result: ChangesResult | null }) {
  return (
    <>
      {result ? (
        <div className="admin-panel__hint">
          {result.state === "ok"
            ? `${result.facts.length} facts from ${result.episodes} extracted sections, versions ${result.versions.join(", ")}`
              + (result.facts_workspace ? `, from the Workspace “${result.facts_workspace}”.` : ".")
            : STATE_TEXT[result.state] ?? result.state}
        </div>
      ) : null}
      {result?.facts.map((fact, index) => (
        <div key={`${fact.citation}-${index}`} className="user-edit-panel__section">
          <div>
            <span className="task-item__badge task-item__badge--secondary">{fact.relation}</span>{" "}
            {fact.version ? <span className="admin-panel__cell--muted">{fact.version} · </span> : null}
            {fact.fact}
          </div>
          <KnowledgeCitation title={fact.source_title} url={fact.source_url} citation={fact.citation}
            section={fact.section} />
        </div>
      ))}
    </>
  );
}
