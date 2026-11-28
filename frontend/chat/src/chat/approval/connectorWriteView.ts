import type { StatusTone } from "../../layout/StatusLabel";

export type ConnectorWriteField = { key: string; label: string; value: string };

export type ConnectorWriteView = {
  action: string;
  title: string;
  connector: string;
  connection: string;
  fields: ConnectorWriteField[];
};

const META_KEYS = new Set(["tool", "connector", "connection"]);

const text = (value: unknown) => (typeof value === "string" ? value.trim() : "");

function words(value: string): string {
  const spaced = value.replace(/[_-]+/g, " ").replace(/\s+/g, " ").trim().toLowerCase();
  return spaced ? spaced[0].toUpperCase() + spaced.slice(1) : "";
}

// The gate writes lists as JSON.
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

export function connectorWriteStatus(status: string | null | undefined): { label: string; tone: StatusTone } {
  const key = String(status || "pending").trim().toLowerCase();
  if (key === "approved") return { label: "Approved", tone: "success" };
  if (key === "rejected" || key === "denied") return { label: "Rejected", tone: "problem" };
  if (key === "expired") return { label: "Expired", tone: "neutral" };
  return { label: "Waiting for you", tone: "attention" };
}
