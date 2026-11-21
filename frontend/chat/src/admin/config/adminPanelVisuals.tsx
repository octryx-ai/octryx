import type { ReactNode } from "react";
import { Icon } from "@iconify/react";
import {
  siBitbucket,
  siConfluence,
  siElasticsearch,
  siGithub,
  siGitlab,
  siGooglecloud,
  siGrafana,
  siJenkins,
  siJira,
  siKubernetes,
  siMatrix,
  siNotion,
  siPostgresql,
  siPrometheus,
  siSonatype,
  siTelegram,
} from "simple-icons";
import { adminBrandIcons } from "../utils/brands";

export const CONNECTOR_ICONS: Record<string, ReactNode> = {
  github: adminBrandIcons.github,
  gitlab: adminBrandIcons.gitlab,
  jira: adminBrandIcons.jira,
  bitbucket: adminBrandIcons.bitbucket,
  confluence: adminBrandIcons.confluence,
  notion: adminBrandIcons.notion,
  sharepoint: (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.8"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <circle cx="8" cy="12" r="4.75" />
      <rect x="12" y="5.5" width="7.5" height="13" rx="1.8" />
      <path d="M6.1 13.6c.72.73 1.66 1.1 2.82 1.1 1.36 0 2.48-.63 3.35-1.88" />
      <path d="M10.9 9.2c-.58-.72-1.42-1.08-2.52-1.08-1.2 0-2.2.45-2.98 1.35" />
    </svg>
  ),
  elasticsearch: adminBrandIcons.elasticsearch,
  aws: (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.7"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <path d="M5 9.5 8 16l2.2-4.8L12.4 16l3-6.5" />
      <path d="M4.5 19.1c4 1.95 10.6 2.23 15 .35" />
      <path d="M18.6 18.35c.92-.08 1.5-.42 1.7-1.03.17-.5.01-1.02-.5-1.57" />
    </svg>
  ),
  azure: (
    <svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
      <path d="M12.22 2.5 6.05 9.88l4.03-.78-5.36 12.4 13.23-16.34-4.25.77L12.22 2.5Z" />
      <path d="m13.46 9.96 3.93-.7 1.9 9.72H11.7z" opacity=".72" />
    </svg>
  ),
  gcp: adminBrandIcons.gcp,
  kubernetes: adminBrandIcons.kubernetes,
  grafana: adminBrandIcons.grafana,
  prometheus: adminBrandIcons.prometheus,
  jenkins: adminBrandIcons.jenkins,
  nexus: adminBrandIcons.nexus,
  postgres: adminBrandIcons.postgres,
  servicenow: (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.8"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <circle cx="12" cy="12" r="8" />
      <path d="M9 9.5c0-1 1-1.8 2.2-1.8 1.8 0 3 1.2 3 2.7 0 2.3-2.7 2.5-2.7 4.3" />
      <circle cx="11.5" cy="17.5" r="0.8" fill="currentColor" stroke="none" />
    </svg>
  ),
  loki: adminBrandIcons.loki,
  system: (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.8"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <path d="M4 6h16v12H4z" />
      <path d="M8 10l2 2-2 2" />
      <path d="M12 14h4" />
    </svg>
  ),
};

export const CONNECTOR_COLORS: Record<string, string> = {
  github: `#${siGithub.hex}`,
  gitlab: `#${siGitlab.hex}`,
  jira: `#${siJira.hex}`,
  bitbucket: `#${siBitbucket.hex}`,
  confluence: `#${siConfluence.hex}`,
  notion: `#${siNotion.hex}`,
  sharepoint: "#0A66C2",
  elasticsearch: `#${siElasticsearch.hex}`,
  aws: "#FF9900",
  azure: "#0078D4",
  gcp: `#${siGooglecloud.hex}`,
  kubernetes: `#${siKubernetes.hex}`,
  grafana: `#${siGrafana.hex}`,
  prometheus: `#${siPrometheus.hex}`,
  jenkins: `#${siJenkins.hex}`,
  nexus: `#${siSonatype.hex}`,
  postgres: `#${siPostgresql.hex}`,
  servicenow: "#81B441",
  loki: "rgba(255, 255, 255, 0.08)",
  system: "#64748B",
};

const CHANNEL_ICONS: Record<string, ReactNode> = {
  email: (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.8"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <rect x="2" y="4" width="20" height="16" rx="2" />
      <path d="M2 7l10 7 10-7" />
    </svg>
  ),
  teams: adminBrandIcons.teams,
  slack: adminBrandIcons.slack,
  telegram: adminBrandIcons.telegram,
  matrix: adminBrandIcons.matrix,
};

const CHANNEL_COLORS: Record<string, string> = {
  email: "#5b7cfa",
  teams: "#6264A7",
  slack: "#4A154B",
  telegram: `#${siTelegram.hex}`,
  matrix: `#${siMatrix.hex}`,
};

const FALLBACK_CHANNEL_ICON = (
  <svg
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    strokeWidth="1.8"
    strokeLinecap="round"
    strokeLinejoin="round"
  >
    <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />
  </svg>
);

function getChannelIconKey(pluginId: string) {
  return Object.keys(CHANNEL_ICONS).find((key) =>
    pluginId.toLowerCase().includes(key),
  );
}

export function renderChannelIcon(pluginId: string): ReactNode {
  const iconKey = getChannelIconKey(pluginId);
  return CHANNEL_ICONS[iconKey ?? ""] ?? FALLBACK_CHANNEL_ICON;
}

export function getChannelIconColor(pluginId: string): string {
  return CHANNEL_COLORS[getChannelIconKey(pluginId) ?? ""] ?? "#6B7280";
}

function getMcpVendorKey(vendor?: string | null, name?: string): string {
  const value = `${vendor || ""} ${name || ""}`.toLowerCase();
  if (value.includes("upstash") || value.includes("context7"))
    return "context7";
  if (value.includes("cloudflare")) return "cloudflare";
  if (value.includes("microsoft") || value.includes("azure")) return "azure";
  if (value.includes("aws")) return "aws";
  if (value.includes("terraform") || value.includes("hashicorp"))
    return "terraform";
  return "generic";
}

export function renderMcpIcon(
  vendor?: string | null,
  name?: string,
): ReactNode {
  switch (getMcpVendorKey(vendor, name)) {
    case "context7":
      return <Icon icon="lucide:book-open-text" width="20" height="20" />;
    case "cloudflare":
      return <Icon icon="lucide:cloud" width="20" height="20" />;
    case "azure":
      return <Icon icon="lucide:server-cog" width="20" height="20" />;
    case "aws":
      return <Icon icon="lucide:cloud-lightning" width="20" height="20" />;
    case "terraform":
      return <Icon icon="lucide:blocks" width="20" height="20" />;
    default:
      return <Icon icon="lucide:plug-zap" width="20" height="20" />;
  }
}

export function getMcpIconColor(vendor?: string | null, name?: string): string {
  switch (getMcpVendorKey(vendor, name)) {
    case "context7":
      return "#10B981";
    case "cloudflare":
      return "#F97316";
    case "azure":
      return "#0078D4";
    case "aws":
      return "#FF9900";
    case "terraform":
      return "#7C3AED";
    default:
      return "#64748B";
  }
}
