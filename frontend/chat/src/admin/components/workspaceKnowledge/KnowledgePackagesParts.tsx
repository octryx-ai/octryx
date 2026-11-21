import type { FormEvent } from "react";
import { KnowledgePackageCatalog } from "./KnowledgePackageCatalog";
import { webSearchApi, workspaceKnowledgeApi } from "./workspaceKnowledgeApi";
import type { CatalogEntry, KnowledgePackage } from "./workspaceKnowledgeTypes";
import type { KnowledgePackagesState } from "./useKnowledgePackages";

// "Let an agent research a package": topic, optional product and versions.
export function PackageResearchForm({ state, onSubmit }: { state: KnowledgePackagesState; onSubmit: (event: FormEvent) => void }) {
  const { topic, setTopic, product, setProduct, versions, setVersions, busy } = state;
  return (
    <form className="user-edit-panel__section knowledge-packages__form" onSubmit={onSubmit}>
      <div className="user-edit-panel__section-label">Let an agent research a package</div>
      {/* The topic is the main field: full width, so its example is never cut off. */}
      <input className="admin-panel__input knowledge-packages__topic" value={topic} onChange={(event) => setTopic(event.target.value)}
        aria-label="Topic" placeholder="Topic, e.g. Spring Boot 3.5 to 4.0 upgrade, or OAuth 2.1 specification" />
      <div className="knowledge-packages__row">
        <input className="admin-panel__input" placeholder="Product (optional hint)" value={product}
          onChange={(event) => setProduct(event.target.value)} />
        <input className="admin-panel__input" placeholder="Versions, comma-separated (optional)" value={versions}
          onChange={(event) => setVersions(event.target.value)} />
        <button type="submit" className="admin-panel__action-btn admin-panel__action-btn--primary" disabled={busy !== null}>
          {busy === "research" ? "Researching…" : "Research"}
        </button>
      </div>
      <div className="admin-panel__hint">
        A governed model names the vendor's entry points and searches only trusted sources and those entry points,
        then picks the authoritative pages and explains each one. A new source waits for you to trust it, and
        nothing is ingested until you approve.
      </div>
    </form>
  );
}

// The selected package: its research rounds, the catalog, further research and the approval.
export function PackageDetail({ state, workspaceId, selected }: { state: KnowledgePackagesState; workspaceId: string; selected: KnowledgePackage }) {
  const { busy, run, instruction, setInstruction, extractGraph, setExtractGraph } = state;
  const id = selected?.id ?? "";
  const rounds = selected?.research.rounds ?? [];
  return (
    <div className="user-edit-panel__section">
      <div className="user-edit-panel__section-label">
        {selected.title}
        <span className="admin-panel__cell--muted"> · {selected.product} {selected.versions.join(", ")} · {selected.state}</span>
      </div>
      <div className="admin-panel__hint">
        {rounds.length} research round{rounds.length === 1 ? "" : "s"}
        {rounds.length ? ` · last queries: ${(rounds[rounds.length - 1].queries ?? []).join(" | ")}` : ""}
        {rounds.length && rounds[rounds.length - 1].search_outcomes?.length
          ? ` · search: ${Array.from(new Set(rounds[rounds.length - 1].search_outcomes)).join(", ")}` : ""}
      </div>

      <KnowledgePackageCatalog
        pkg={selected}
        busy={busy !== null}
        onTrustSource={(pattern) => void run("trust", async () => {
          await webSearchApi.put(workspaceId, {
            pattern, state: "trusted", scope: "workspace", products: [selected.product],
            reason: `Trusted from the catalog of ${selected.title}.`,
          });
          return workspaceKnowledgeApi.get(workspaceId, id);
        }, () => `Trusted ${pattern} for ${selected.product} in this workspace.`)}
        onDecide={(decisions) => void run("decide", () => workspaceKnowledgeApi.decide(workspaceId, id, decisions),
          (pkg) => (pkg.held_untrusted?.length ? `${pkg.held_untrusted.length} documents wait for their source to be trusted.` : ""))}
        onAdd={(entry: CatalogEntry) => void run("add", () => workspaceKnowledgeApi.addDocument(workspaceId, id, entry))}
        onEdit={(documentId, entry) => void run("edit", () => workspaceKnowledgeApi.editDocument(workspaceId, id, documentId, entry))}
        onRemove={(documentId) => void run("remove", () => workspaceKnowledgeApi.removeDocument(workspaceId, id, documentId))}
      />

      <div className="user-edit-panel__section-label" style={{ marginTop: "0.8rem" }}>Commission further research</div>
      <div style={{ display: "grid", gridTemplateColumns: "minmax(0, 1fr) auto", gap: "0.4rem" }}>
        <input className="admin-panel__input" value={instruction} onChange={(event) => setInstruction(event.target.value)}
          placeholder="e.g. also find the 4.1 release notes and the Actuator migration notes" />
        <button type="button" className="admin-panel__action-btn" disabled={busy !== null || instruction.trim().length < 3}
          onClick={() => void run("more", () => workspaceKnowledgeApi.researchMore(workspaceId, id, instruction.trim()),
            (pkg) => `The agent added ${pkg.added ?? 0} new proposals.`)}>
          {busy === "more" ? "Researching…" : "Research more"}
        </button>
      </div>

      <div className="user-edit-panel__row-end" style={{ marginTop: "0.8rem", gap: "0.6rem", alignItems: "center" }}>
        <label className="admin-panel__hint">
          <input type="checkbox" checked={extractGraph} onChange={(event) => setExtractGraph(event.target.checked)} />{" "}
          then extract into the knowledge graph
        </label>
        <button type="button" className="admin-panel__action-btn admin-panel__action-btn--primary" disabled={busy !== null}
          onClick={() => void run("approve", () => workspaceKnowledgeApi.approvePackage(workspaceId, id, extractGraph),
            (pkg) => `Ingested ${pkg.counts?.ingested ?? 0}, failed ${pkg.counts?.failed ?? 0}` +
              (pkg.graph_revisions_owed ? `; ${pkg.graph_revisions_owed} revisions queued for the graph.` : "."))}>
          {busy === "approve" ? "Ingesting…" : "Approve & ingest accepted sources"}
        </button>
      </div>
    </div>
  );
}
