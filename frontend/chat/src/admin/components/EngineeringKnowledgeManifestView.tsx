// Engineering knowledge packs: the manifest view of a pack version and its blockers.
import { useState } from "react";
import type { EngineeringKnowledgePackVersion } from "../types/engineeringKnowledgeTypes";

export function ManifestView({
  manifest,
  packKey,
  version,
}: {
  manifest: EngineeringKnowledgePackVersion["manifest"];
  packKey: string;
  version: number;
}) {
  const [open, setOpen] = useState(false);
  if (!manifest) return null;
  const json = JSON.stringify(manifest, null, 2);
  return (
    <div style={{ marginTop: "0.5rem" }}>
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          marginBottom: "0.35rem",
        }}
      >
        <span style={{ fontSize: "var(--ds-text-xs)", color: "var(--text-muted)" }}>
          Manifest · {(json.length / 1024).toFixed(1)} KB
        </span>
        <button
          type="button"
          onClick={() => setOpen((o) => !o)}
          style={{
            background: "none",
            border: "1px solid var(--border-soft)",
            borderRadius: "var(--ds-radius-sm)",
            padding: "0.15rem 0.5rem",
            fontSize: "var(--ds-text-2xs)",
            color: "var(--text-muted)",
            cursor: "pointer",
          }}
        >
          {open ? "Hide" : "View JSON"}
        </button>
      </div>
      {open && (
        <>
          <pre
            style={{
              background: "rgba(0,0,0,0.25)",
              border: "1px solid var(--border-soft)",
              borderRadius: "var(--ds-radius-md)",
              padding: "0.6rem 0.8rem",
              fontSize: "var(--ds-text-2xs)",
              fontFamily: "monospace",
              color: "var(--text-secondary)",
              maxHeight: "300px",
              overflowY: "auto",
              margin: 0,
              whiteSpace: "pre-wrap",
              wordBreak: "break-all",
            }}
          >
            {json}
          </pre>
          <div style={{ display: "flex", gap: "0.4rem", marginTop: "0.4rem" }}>
            <button
              type="button"
              className="admin-panel__action-btn"
              style={{ fontSize: "var(--ds-text-2xs)" }}
              onClick={() => {
                const blob = new Blob([json], { type: "application/json" });
                const url = URL.createObjectURL(blob);
                const a = document.createElement("a");
                a.href = url;
                a.download = `${packKey}-v${version}-manifest.json`;
                a.click();
                URL.revokeObjectURL(url);
              }}
            >
              Download JSON
            </button>
            <button
              type="button"
              className="admin-panel__action-btn"
              style={{ fontSize: "var(--ds-text-2xs)" }}
              onClick={() => {
                navigator.clipboard.writeText(json).catch(() => null);
              }}
            >
              Copy
            </button>
          </div>
        </>
      )}
    </div>
  );
}

export function BlockersList({
  blockers,
}: {
  blockers: Array<{ code?: string; message?: string }>;
}) {
  if (!blockers.length) return null;
  return (
    <div style={{ marginTop: "0.5rem" }}>
      {blockers.map((b, i) => (
        <div
          key={i}
          style={{ fontSize: "var(--ds-text-xs)", color: "var(--status-error)", padding: "0.2rem 0" }}
        >
          {b.code ? (
            <span style={{ fontFamily: "monospace", marginRight: "0.4rem" }}>
              [{b.code}]
            </span>
          ) : null}
          {b.message ?? "Quality gate blocked"}
        </div>
      ))}
    </div>
  );
}
