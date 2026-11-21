import type { FormEvent } from "react";
import { PackageDetail, PackageResearchForm } from "./KnowledgePackagesParts";
import { useKnowledgePackages } from "./useKnowledgePackages";
import { splitProducts } from "./workspaceKnowledgeRequest";
import { workspaceKnowledgeApi } from "./workspaceKnowledgeApi";
import "./knowledge-packages.css";

// Knowledge packages as a virtual worker builds them: an agent researches the sources, the author curates
// the catalog, commissions further research, and approves what is ingested.
export function KnowledgePackagesPanel({ workspaceId }: { workspaceId: string }) {
  const state = useKnowledgePackages(workspaceId);
  const { packages, selectedId, setSelectedId, topic, product, versions, message, run } = state;

  const research = (event: FormEvent) => {
    event.preventDefault();
    if (!topic.trim()) return;
    const hint = splitProducts(product)[0] ?? null;
    const hintVersions = versions.split(",").map((item) => item.trim()).filter(Boolean);
    void run("research", () => workspaceKnowledgeApi.researchPackage(workspaceId, {
      topic: topic.trim(), product: hint, versions: hintVersions.length ? hintVersions : null,
    }), (pkg) => `The agent proposed ${pkg.documents.length} sources. Review the catalog, then approve.`);
  };

  const selected = packages.find((item) => item.id === selectedId) ?? null;

  return (
    <div>
      <PackageResearchForm state={state} onSubmit={research} />

      {message ? <div className="admin-panel__hint" role="status">{message}</div> : null}

      <div style={{ display: "flex", gap: "0.35rem", flexWrap: "wrap", margin: "0.5rem 0" }}>
        {packages.map((item) => (
          <button key={item.id} type="button" onClick={() => setSelectedId(item.id)}
            className={`admin-panel__action-btn${item.id === selectedId ? " admin-panel__action-btn--primary" : ""}`}>
            {item.title} · {item.state}
          </button>
        ))}
      </div>

      {selected ? <PackageDetail state={state} workspaceId={workspaceId} selected={selected} /> : null}
    </div>
  );
}
