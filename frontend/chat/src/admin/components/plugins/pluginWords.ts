import type { PluginInstall, PluginStatus, SummaryLine } from "./pluginsApi";

export const plural = (count: number, one: string, many = `${one}s`) => `${count} ${count === 1 ? one : many}`;

const CONNECTION_NAMES: Record<string, string> = {
  jira: "Jira", confluence: "Confluence", github: "GitHub", gitlab: "GitLab", bitbucket: "Bitbucket", scm: "Git hosting",
  slack: "Slack", teams: "Microsoft Teams", email: "Email", sharepoint: "SharePoint",
};

export function connectionName(kind: string): string {
  const key = kind.trim().toLowerCase();
  return CONNECTION_NAMES[key] ?? (key ? key.charAt(0).toUpperCase() + key.slice(1).replace(/[_-]+/g, " ") : "");
}

export function listWords(items: string[]): string {
  if (items.length <= 1) return items.join("");
  return `${items.slice(0, -1).join(", ")} and ${items[items.length - 1]}`;
}

export function statusText(status: PluginStatus): string {
  return status === "active" ? "On" : "Off";
}

const DATE = new Intl.DateTimeFormat("en-GB", { day: "numeric", month: "short", year: "numeric" });

export function installedText(install: Pick<PluginInstall, "installed_by_name" | "installed_at">): string {
  const who = install.installed_by_name || "Unknown person";
  const when = install.installed_at ? DATE.format(new Date(install.installed_at)) : "";
  return when ? `${who} · ${when}` : who;
}

const strings = (value: unknown): string[] => (Array.isArray(value) ? value.map(String).filter(Boolean) : []);

export function summaryText(line: SummaryLine): string {
  const params = line.params ?? {};
  switch (line.key) {
    case "plugins.summary.uses": {
      const used = strings(params.connections).map(connectionName);
      return used.length ? `Uses ${listWords(used)} of this Workspace` : line.text;
    }
    case "plugins.summary.writes": {
      const writes = strings(params.writes).map(connectionName);
      return writes.length ? `Writes to ${listWords(writes)}, asks every time` : line.text;
    }
    case "plugins.summary.pages": {
      const pages = strings(params.pages);
      return pages.length ? `Adds ${pages.length === 1 ? "the page" : "the pages"} ${listWords(pages)}` : line.text;
    }
    case "plugins.summary.connects": {
      const hosts = strings(params.hosts);
      return hosts.length ? `Connects to ${listWords(hosts)}` : line.text;
    }
    default:
      return line.text;
  }
}
