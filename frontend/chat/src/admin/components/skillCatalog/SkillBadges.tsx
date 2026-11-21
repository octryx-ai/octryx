import type { ReactNode } from "react";

import { SURFACES } from "./skillCatalogTypes";
import { trustLabel } from "./skillCatalogModel";
import type { SourceRef, Surface } from "./skillCatalogTypes";

// Small shared pieces of the catalog list and the detail page (mock `kindBadge`, `trustBadge`, `surf`, `checkRows`).

export function KindBadge({ kind }: { kind: string }) {
  return kind === "mcp_server" ? <span className="skills__kind">MCP server</span> : null;
}

export function TrustBadge({ source }: { source: Pick<SourceRef, "trust" | "kind"> | null }) {
  if (!source) return null;
  const official = source.trust === "official" && source.kind !== "upload";
  return <span className={`work-badge ${official ? "work-badge--running" : "work-badge--neutral"}`}>{trustLabel(source)}</span>;
}

const SHORT: Record<Surface, string> = { platform_chat: "Chat", octryx_claude: "octryx-claude" };

export function SurfaceBadges({ available }: { available: Partial<Record<Surface, boolean>> }) {
  const on = SURFACES.filter((surface) => available[surface]);
  return (
    <span className="skills__surfaces">
      {on.map((surface) => <span key={surface} className="work-badge work-badge--neutral">{SHORT[surface]}</span>)}
      {on.length ? null : <span className="admin-panel__cell--muted">nowhere</span>}
    </span>
  );
}

export type CheckTone = "ok" | "wa" | "er" | "in";
const MARKS: Record<CheckTone, string> = { ok: "✓", wa: "!", er: "✕", in: "i" };

/** One row of an automated check list: icon, bold title, text and an optional hint line. */
export function CheckRow({ tone, title, children, hint, icon }: {
  tone: CheckTone;
  title?: ReactNode;
  children?: ReactNode;
  hint?: ReactNode;
  icon?: string;
}) {
  return (
    <div className="skills__check">
      <span className={`skills__check-i skills__${tone}`}>{icon ?? MARKS[tone]}</span>
      <span>
        {title ? <b>{title}</b> : null}{title && children ? " — " : null}{children}
        {hint ? <div className="skills__hint">{hint}</div> : null}
      </span>
    </div>
  );
}
