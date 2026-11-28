// The model's raw fields are never shown, only the server's masked body.

export type RestRequestField = { key: string; label: string; value: string };

export type RestRequestView = {
  method: string;
  path: string;
  host: string;
  url: string;
  api: string;
  operation: string;
  title: string;
  target: string;
  connection: string;
  noConnection: boolean;
  outsideAccess: boolean;
  scope: string[];
  headers: string[];
  fields: RestRequestField[];
  bodyJson: string;
};

const record = (value: unknown): Record<string, unknown> | null =>
  value && typeof value === "object" && !Array.isArray(value) ? (value as Record<string, unknown>) : null;
const text = (value: unknown) => (typeof value === "string" ? value.trim() : "");

export const isRestTool = (tool: unknown) => /^rest__/.test(text(tool));

function detailLines(raw: unknown): Map<string, string> {
  const lines = new Map<string, string>();
  for (const line of Array.isArray(raw) ? raw : []) {
    const value = String(line ?? "");
    const cut = value.indexOf(": ");
    if (cut > 0 && !lines.has(value.slice(0, cut))) lines.set(value.slice(0, cut), value.slice(cut + 2));
  }
  return lines;
}

function splitUrl(url: string): { host: string; path: string } {
  try {
    const parsed = new URL(url);
    return { host: parsed.host, path: `${parsed.pathname}${parsed.search}` || "/" };
  } catch {
    return { host: "", path: url || "/" };
  }
}

function readBody(preview: Record<string, unknown>, lines: Map<string, string>): unknown {
  if ("body" in preview) return preview.body;
  const line = lines.get("body");
  if (line === undefined) return undefined;
  try {
    return JSON.parse(line);
  } catch {
    return line;
  }
}

function words(key: string): string {
  const spaced = key.replace(/[_-]+/g, " ").replace(/\s+/g, " ").trim();
  return spaced ? spaced[0].toUpperCase() + spaced.slice(1) : key;
}

function shownValue(value: unknown): string {
  if (value === null || value === undefined) return "";
  if (typeof value === "string") return value;
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  return JSON.stringify(value);
}

function scopeLines(line: string | undefined): string[] {
  if (!line) return [];
  return line
    .split(", ")
    .map((part) => part.trim())
    .filter(Boolean)
    .map((part) => {
      const cut = part.indexOf("=");
      return cut > 0 ? `${part.slice(0, cut)} = ${part.slice(cut + 1)}` : part;
    });
}

export function restRequestView(raw: Record<string, unknown> | null | undefined): RestRequestView | null {
  const preview = record(raw);
  if (!preview) return null;
  const lines = detailLines(preview.details);
  const isRest = preview.kind === "rest_request" || isRestTool(preview.tool) || isRestTool(preview.toolName);
  if (!isRest) return null;
  const request = lines.get("request") ?? "";
  const requestMethod = request.split(" ")[0] ?? "";
  const method = (text(preview.method) || requestMethod || "").toUpperCase();
  const url = text(preview.url) || request.slice(requestMethod.length).trim();
  const { host, path } = splitUrl(url);
  const api = text(preview.api) || lines.get("api") || "";
  const operation = text(preview.operation) || lines.get("operation") || "";
  const target = [api, operation].filter(Boolean).join(" › ");
  const connectionLine = lines.get("connection") ?? "";
  const noConnection = !text(preview.connection) && /^none active/.test(connectionLine);
  const connection = text(preview.connection) || (noConnection ? "" : connectionLine);
  const headers = Array.isArray(preview.header_names)
    ? preview.header_names.map((name) => String(name)).filter(Boolean)
    : (lines.get("headers") ?? "").split(",").map((name) => name.trim()).filter(Boolean);
  const body = readBody(preview, lines);
  const bodyRecord = record(body);
  const fields = bodyRecord
    ? Object.entries(bodyRecord).map(([key, value]) => ({ key, label: words(key), value: shownValue(value) }))
    : [];
  const nested = bodyRecord ? Object.values(bodyRecord).some((value) => value !== null && typeof value === "object") : false;
  const bodyJson = body === undefined || body === null ? "" : bodyRecord && !nested ? "" : JSON.stringify(body, null, 2);
  return {
    method,
    path,
    host,
    url,
    api,
    operation,
    title: [method, path].filter(Boolean).join(" ") + (target ? ` on ${target}` : ""),
    target,
    connection,
    noConnection,
    outsideAccess: /^outside your access/.test(lines.get("scope") ?? ""),
    scope: scopeLines(lines.get("scope set by Octryx")),
    headers,
    fields,
    bodyJson,
  };
}

export function restRequestLines(view: RestRequestView): string[] {
  return [
    view.noConnection ? "No active connection for this Workspace: the call will be refused." : "",
    view.outsideAccess ? "Outside your access to this operation: the call will be refused." : "",
    view.url ? `Sent to ${view.url}` : "",
    view.scope.length ? `Scope set by Octryx: ${view.scope.join(" · ")}` : "",
    view.headers.length ? `Header names: ${view.headers.join(", ")}` : "",
  ].filter(Boolean);
}

export const REST_REQUEST_NOTE = "Credentials are never shown. Values that look like secrets are stored masked and show as [redacted].";
