import type { ReactNode } from "react";

import {
  CONNECTOR_COLORS,
  CONNECTOR_ICONS,
} from "../../config/adminPanelVisuals";
import { adminBrandColors, adminBrandIcons } from "../../utils/brands";

// The brand square used on every Automation card (automation concept v2): the real simple-icons glyph in its brand
// colour, with plain glyphs only where no brand mark exists (any JSON, SQL Server, actions).
const WEBHOOK_GLYPH = (
  <svg
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    strokeWidth="1.8"
    strokeLinecap="round"
    strokeLinejoin="round"
  >
    <path d="M9 7a3 3 0 1 1 4.5 2.6L16 14" />
    <circle cx="17.5" cy="16.5" r="2.5" />
    <path d="M6.5 14.5 5 17a2.5 2.5 0 1 0 4 1.5h6" />
  </svg>
);
const DATABASE_GLYPH = (
  <svg
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    strokeWidth="1.8"
    strokeLinecap="round"
    strokeLinejoin="round"
  >
    <ellipse cx="12" cy="6" rx="7" ry="3" />
    <path d="M5 6v12c0 1.7 3.1 3 7 3s7-1.3 7-3V6" />
    <path d="M5 12c0 1.7 3.1 3 7 3s7-1.3 7-3" />
  </svg>
);
const ACTION_GLYPH = (
  <svg
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    strokeWidth="1.8"
    strokeLinecap="round"
    strokeLinejoin="round"
  >
    <path d="M7 4l12 8-12 8z" />
  </svg>
);

const ICONS: Record<string, { glyph: ReactNode; color: string }> = {
  alertmanager: {
    glyph: adminBrandIcons.prometheus,
    color: adminBrandColors.prometheus,
  },
  prometheus: {
    glyph: adminBrandIcons.prometheus,
    color: adminBrandColors.prometheus,
  },
  grafana: { glyph: adminBrandIcons.grafana, color: adminBrandColors.grafana },
  datadog: { glyph: adminBrandIcons.datadog, color: adminBrandColors.datadog },
  pagerduty: {
    glyph: adminBrandIcons.pagerduty,
    color: adminBrandColors.pagerduty,
  },
  sentry: { glyph: adminBrandIcons.sentry, color: adminBrandColors.sentry },
  generic: { glyph: WEBHOOK_GLYPH, color: "#64748B" },
  webhook: { glyph: WEBHOOK_GLYPH, color: "#64748B" },
  jira_change: { glyph: CONNECTOR_ICONS.jira, color: CONNECTOR_COLORS.jira },
  servicenow_change: {
    glyph: CONNECTOR_ICONS.servicenow,
    color: CONNECTOR_COLORS.servicenow,
  },
  postgresql: {
    glyph: adminBrandIcons.postgres,
    color: adminBrandColors.postgres,
  },
  mysql: { glyph: adminBrandIcons.mysql, color: adminBrandColors.mysql },
  mariadb: { glyph: adminBrandIcons.mariadb, color: adminBrandColors.mariadb },
  snowflake: {
    glyph: adminBrandIcons.snowflake,
    color: adminBrandColors.snowflake,
  },
  mssql: { glyph: DATABASE_GLYPH, color: "#A91D22" },
  database: { glyph: DATABASE_GLYPH, color: "#475569" },
  action: { glyph: ACTION_GLYPH, color: "#64748B" },
  teams: { glyph: adminBrandIcons.teams, color: "#6264A7" },
  slack: { glyph: adminBrandIcons.slack, color: "#4A154B" },
};

export function automationIconKnown(kind: string): boolean {
  return kind in ICONS;
}

export function AutomationIcon({
  kind,
  small = false,
}: {
  kind: string;
  small?: boolean;
}) {
  const icon = ICONS[kind] ?? ICONS.webhook;
  return (
    <span
      className={`automation-icon${small ? " automation-icon--small" : ""}`}
      style={{ background: icon.color }}
      aria-hidden="true"
    >
      {icon.glyph}
    </span>
  );
}
