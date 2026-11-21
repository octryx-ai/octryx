// A chat's connector write waits for the person's confirmation, one call at a time (rule chat_connector_write).
// The gate's preview names the tool, the connector, the connection and every written field as "key: value" lines
// (backend/app/services/tool_approval_gate.py `_chat_write_preview`). This turns it into what the card shows: what is
// written, where, and the fields. Pure, so the card and its tests share it.
import type { StatusTone } from "../../layout/StatusLabel";

export type ConnectorWriteField = { key: string; label: string; value: string };

export type ConnectorWriteView = {
  // "Create Jira ticket": the tool in words.
  action: string;
  // The tool's own preview title when it has one ("Create Epic Kitchen helper v1 in MM"), otherwise the action.
  title: string;
  // "Jira" and the connection's name ("Jira", "default").
  connector: string;
  connection: string;
  // Every written field, in the order the gate listed them.
  fields: ConnectorWriteField[];
};

const META_KEYS = new Set(["tool", "connector", "connection"]);

const text = (value: unknown) => (typeof value === "string" ? value.trim() : "");

function words(value: string): string {
  const spaced = value.replace(/[_-]+/g, " ").replace(/\s+/g, " ").trim().toLowerCase();
  return spaced ? spaced[0].toUpperCase() + spaced.slice(1) : "";
}

// A list of plain values ("[\"a\",\"b\"]", as the gate writes JSON) reads as "a, b"; anything else stays as written.
function readable(value: string): string {
  if (!value.startsWith("[")) return value;
  try {
    const list = JSON.parse(value);
    if (Array.isArray(list) && list.every((item) => ["string", "number", "boolean"].includes(typeof item))) {
      return list.join(", ");
    }
  } catch {
    // Not JSON: shown as written.
  }
  return value;
}

function capitalised(value: string): string {
  return value ? value[0].toUpperCase() + value.slice(1) : "";
}

/** The card's view of a chat connector write, or null for every other approval. */
export function connectorWriteView(
  preview: Record<string, unknown> | null | undefined,
  toolName?: string | null,
): ConnectorWriteView | null {
  if (!preview || typeof preview !== "object" || !("connection" in preview)) return null;
  const lines = Array.isArray(preview.details) ? preview.details.map((line) => String(line ?? "")) : [];
  const meta: Record<string, string> = {};
  const fields: ConnectorWriteField[] = [];
  const seen = new Set<string>();
  for (const line of lines) {
    if (!line.trim() || seen.has(line)) continue;
    seen.add(line);
    const cut = line.indexOf(": ");
    const key = cut > 0 ? line.slice(0, cut).trim() : "";
    const value = cut > 0 ? line.slice(cut + 2) : line;
    if (META_KEYS.has(key)) {
      meta[key] = value.trim();
      continue;
    }
    fields.push({ key, label: key ? words(key) : "", value: readable(value) });
  }
  if (!("connector" in meta)) return null;
  const connector = capitalised(meta.connector);
  const tool = text(preview.toolName) || text(toolName) || meta.tool || "";
  // "create_jira_ticket" -> "Create jira ticket" -> "Create Jira ticket": the connector keeps its name.
  let action = words(tool) || "Write";
  if (connector) action = action.replace(new RegExp(`\\b${meta.connector}\\b`, "i"), connector);
  const own = text(preview.title);
  return {
    action,
    title: own || action,
    connector,
    connection: text(preview.connection) || meta.connection || "",
    fields,
  };
}

/** The card's state in words and its tone: only the pending one asks for attention. */
export function connectorWriteStatus(status: string | null | undefined): { label: string; tone: StatusTone } {
  const key = String(status || "pending").trim().toLowerCase();
  if (key === "approved") return { label: "Approved", tone: "success" };
  if (key === "rejected" || key === "denied") return { label: "Rejected", tone: "problem" };
  if (key === "expired") return { label: "Expired", tone: "neutral" };
  return { label: "Waiting for you", tone: "attention" };
}
