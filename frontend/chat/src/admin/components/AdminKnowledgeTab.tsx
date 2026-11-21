import { useState } from "react";
import type { AdminKnowledgeTabProps } from "./knowledgeTypes";
import { AdminEngineeringKnowledgePacksPanel } from "./AdminEngineeringKnowledgePacksPanel";
import { AdminEngineeringKnowledgeReviewPanel } from "./AdminEngineeringKnowledgeReviewPanel";
import { AdminEngineeringKnowledgeQualityPanel } from "./AdminEngineeringKnowledgeQualityPanel";
import { AdminEngineeringKnowledgeFederationPanel } from "./AdminEngineeringKnowledgeFederationPanel";

// Governed Knowledge lives in the Workspace Knowledge tab. The entity graph has its own page
// (Knowledge → Graph), and session memory lives in Admin › Knowledge › Memory, so neither is a sub-tab here.
type KnowledgeTab = "packs" | "review" | "quality" | "federation";

// ─── Sub-tab bar ─────────────────────────────────────────────────────────────

const SUB_TABS: Array<{ id: KnowledgeTab; label: string }> = [
  { id: "packs", label: "Engineering Packs" },
  { id: "review", label: "Engineering Review" },
  { id: "quality", label: "Quality" },
  { id: "federation", label: "Federation" },
];

// ─── Main Knowledge Tab ──────────────────────────────────────────────────────

export function AdminKnowledgeTab({ ctx }: { ctx: Record<string, unknown> }) {
  const p = ctx as AdminKnowledgeTabProps;
  const [activeSubTab, setActiveSubTab] = useState<KnowledgeTab>("packs");

  return (
    <div>
      {/* Sub-tab bar */}
      <div
        style={{
          display: "flex",
          gap: "0",
          borderBottom: "1px solid var(--border-soft)",
          marginBottom: "0.8rem",
        }}
      >
        {SUB_TABS.map((tab) => (
          <button
            key={tab.id}
            type="button"
            onClick={() => setActiveSubTab(tab.id)}
            style={{
              background: "none",
              border: "none",
              borderBottom: `2px solid ${activeSubTab === tab.id ? "var(--accent)" : "transparent"}`,
              color:
                activeSubTab === tab.id
                  ? "var(--text-primary)"
                  : "var(--text-secondary)",
              padding: "0.5rem 1rem",
              fontSize: "var(--ds-text-sm)",
              fontWeight: activeSubTab === tab.id ? 600 : 400,
              cursor: "pointer",
              transition: "all 0.15s",
            }}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {activeSubTab === "packs" ? (
        <AdminEngineeringKnowledgePacksPanel ctx={p} />
      ) : activeSubTab === "review" ? (
        <AdminEngineeringKnowledgeReviewPanel />
      ) : activeSubTab === "quality" ? (
        <AdminEngineeringKnowledgeQualityPanel />
      ) : (
        <AdminEngineeringKnowledgeFederationPanel />
      )}
    </div>
  );
}
