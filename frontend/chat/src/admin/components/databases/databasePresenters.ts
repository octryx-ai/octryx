// Databases page: table states and recent queries in words. Pure: no React.
import type { StatusTone } from "../../../layout/StatusLabel";
import { healthPhrase, healthTone, type StoredHealth } from "../../utils/healthPhrase";

export const DATABASE_TYPE_LABELS: Record<string, string> = {
  postgresql: "PostgreSQL",
  postgres: "PostgreSQL",
  mysql: "MySQL",
  mariadb: "MariaDB",
  mssql: "SQL Server",
  snowflake: "Snowflake",
  sqlite: "SQLite",
};

export function databaseTypeLabel(dbType: string): string {
  return DATABASE_TYPE_LABELS[dbType] ?? dbType;
}

export function databaseIconKind(dbType: string): string {
  if (dbType === "postgres") return "postgresql";
  return ["postgresql", "mysql", "mariadb", "mssql", "snowflake"].includes(dbType) ? dbType : "database";
}

export type DatabaseCard = {
  id: string;
  name: string;
  db_type: string;
  is_active: boolean;
  tool_count: number;
  health?: StoredHealth;
  public_fields?: Record<string, unknown>;
};

export function databaseNeedsAttention(connector: DatabaseCard): boolean {
  return connector.is_active && (healthTone(connector.health) === "error" || connector.tool_count === 0);
}

export function databaseStatus(connector: DatabaseCard): { text: string; tone: "ok" | "error" | "muted" | "warn" } {
  if (connector.is_active && connector.tool_count === 0) {
    return { text: "Needs a query tool · agents can't use it yet", tone: "warn" };
  }
  return { text: healthPhrase(connector.health, connector.is_active), tone: connector.is_active ? healthTone(connector.health) : "muted" };
}

/** The table's state label: the first words of the status line, the whole line as its reason. A paused database
 * is a normal state (neutral); a failing check is a problem; a database without a query tool needs an admin. */
export function databaseState(connector: DatabaseCard): { label: string; tone: StatusTone; title: string } {
  const status = databaseStatus(connector);
  const label = status.text.split(" · ")[0];
  const tone: StatusTone = status.tone === "error" ? "problem" : status.tone === "warn" ? "attention" : "neutral";
  return { label, tone, title: status.text === label ? "" : status.text };
}

export type RecentQuery = {
  id: string;
  tool: string;
  database: string;
  status: string;
  failure_category: string;
  rows: number;
  limit_reached: boolean;
  who: string;
  workspace: string;
  started_at: string | null;
};

export function queryLine(query: RecentQuery): string {
  const who = [query.who && `by ${query.who}`, query.workspace && `in ${query.workspace}`].filter(Boolean).join(" ");
  if (query.status !== "succeeded" && query.status !== "success") {
    return `${who ? `${who} · ` : ""}failed${query.failure_category ? ` (${query.failure_category.replace(/_/g, " ")})` : ""}`;
  }
  const rows = `${query.rows} row${query.rows === 1 ? "" : "s"}${query.limit_reached ? " (limit reached, answer cut)" : ""}`;
  return who ? `${who} · ${rows}` : rows;
}

const failed = (query: RecentQuery) => query.status !== "succeeded" && query.status !== "success";

/** Who ran a recent query and where ("agent-user in Ops"); empty when unknown. */
export function queryBy(query: RecentQuery): string {
  return [query.who, query.workspace && `in ${query.workspace}`].filter(Boolean).join(" ");
}

/** The result cell of a recent query: rows (and a cut answer) or the failure in words. */
export function queryResult(query: RecentQuery): { failed: boolean; text: string } {
  if (failed(query)) return { failed: true, text: query.failure_category ? query.failure_category.replace(/_/g, " ") : "" };
  return { failed: false, text: `${query.rows} row${query.rows === 1 ? "" : "s"}${query.limit_reached ? " (limit reached, answer cut)" : ""}` };
}
