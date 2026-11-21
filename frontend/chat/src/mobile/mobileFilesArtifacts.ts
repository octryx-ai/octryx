// Files, code changes and artifacts a session made, and how the phone opens each kind.

/** The code changes of a chat's device jobs: each Edit/Write/MultiEdit with its file and the diff the Mac sent. */
export type CodeChange = {
  key: string;
  tool: string;
  file: string;
  diff: string;
};

export function codeChanges(
  events: { seq: number; type: string; body: Record<string, unknown> }[],
): CodeChange[] {
  return events.flatMap((event) => {
    const body = event.body ?? {};
    const tool = typeof body.tool === "string" ? body.tool : "";
    if (
      body.kind !== "tool_use" ||
      !["Edit", "Write", "MultiEdit", "NotebookEdit"].includes(tool)
    )
      return [];
    const file =
      typeof body.input_preview === "string" ? body.input_preview : "";
    const diff = typeof body.diff === "string" ? body.diff : "";
    return [{ key: `${event.seq}`, tool, file, diff }];
  });
}

// Files a turn made on the Mac: the Mac lists them by name after each turn; the person opens one
// and the platform fetches it from the Mac on demand.
export type MacFile = {
  key: string;
  jobId: string;
  path: string;
  name: string;
  size: number;
};

export function macFiles(
  jobs: {
    id: string;
    events: { seq: number; body: Record<string, unknown> }[];
  }[],
): MacFile[] {
  const seen = new Set<string>();
  const out: MacFile[] = [];
  for (const job of [...jobs].reverse()) {
    for (const event of [...job.events].reverse()) {
      const body = event.body ?? {};
      if (body.kind !== "files" || !Array.isArray(body.files)) continue;
      for (const raw of body.files) {
        const item = (raw ?? {}) as Record<string, unknown>;
        const path = typeof item.path === "string" ? item.path : "";
        const key = `${job.id}:${path}`;
        if (!path || seen.has(key)) continue;
        seen.add(key);
        out.push({
          key,
          jobId: job.id,
          path,
          name: path.split("/").pop() || path,
          size: typeof item.size === "number" ? item.size : 0,
        });
      }
    }
  }
  return out;
}

const IMAGE_FILE = /\.(png|jpe?g|gif|webp)$/i;
const PAGE_FILE = /\.(html?|svg)$/i;
const TEXT_FILE =
  /\.(txt|md|markdown|csv|tsv|json|ya?ml|toml|log|py|tsx?|jsx?|java|kt|go|rs|rb|sh|sql|xml|html?|svg|css|ini|cfg|conf|diff|patch)$/i;

/** How the app shows a fetched file: a picture, a page (HTML/SVG, sandboxed), text, or only a download. */
export function macFileKind(name: string): "image" | "page" | "text" | "download" {
  if (IMAGE_FILE.test(name)) return "image";
  if (PAGE_FILE.test(name)) return "page";
  if (TEXT_FILE.test(name)) return "text";
  return "download";
}

export function fileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

// Artifacts: pages and designs a session made.
// - Mac turns: Claude Code's own artifacts (published pages on claude.ai) are read from the turn's tool results; the
//   files a turn wrote (HTML, SVG) come with the "files" event and open in MacFiles.
// - Server chats: the platform lists them per tool call (`toolEvents[].artifacts`); pages and Office files open
//   through the preview, diagrams as a picture.
const CLAUDE_ARTIFACT_URL = /https:\/\/claude\.ai\/(?:code\/)?artifact\/[A-Za-z0-9_-]{6,80}/g;

export type ClaudeArtifact = { key: string; url: string; tool: string };

export function claudeArtifacts(
  jobs: { events: { seq: number; body: Record<string, unknown> }[] }[],
): ClaudeArtifact[] {
  const seen = new Set<string>();
  const out: ClaudeArtifact[] = [];
  for (const job of jobs) {
    const tools = new Map<string, string>();
    for (const event of job.events) {
      const body = event.body ?? {};
      if (body.kind === "tool_use" && typeof body.tool_use_id === "string")
        tools.set(body.tool_use_id, typeof body.tool === "string" ? body.tool : "");
      if (body.kind !== "tool_result" || body.is_error || typeof body.output !== "string") continue;
      const tool = tools.get(String(body.tool_use_id ?? "")) ?? "";
      if (tool !== "Artifact") continue; // only Claude Code's own publish tool, never a link some text mentions
      for (const match of body.output.match(CLAUDE_ARTIFACT_URL) ?? []) {
        if (seen.has(match)) continue;
        seen.add(match);
        out.push({ key: match, url: match, tool });
      }
    }
  }
  return out.reverse();
}

export type ServerArtifact = {
  key: string;
  name: string;
  path: string;
  kind: "page" | "diagram" | "office" | "other";
};

const OFFICE_FILE = /\.(docx?|xlsx?|pptx?|odt|ods|odp)$/i;

export function serverArtifacts(messages: unknown[]): ServerArtifact[] {
  const seen = new Set<string>();
  const out: ServerArtifact[] = [];
  for (const raw of Array.isArray(messages) ? messages : []) {
    const events = (raw as { toolEvents?: unknown } | null)?.toolEvents;
    for (const event of Array.isArray(events) ? events : []) {
      const artifacts = (event as { artifacts?: unknown } | null)?.artifacts;
      for (const item of Array.isArray(artifacts) ? artifacts : []) {
        const entry = (item ?? {}) as Record<string, unknown>;
        const path = typeof entry.path === "string" ? entry.path : "";
        if (!path || seen.has(path)) continue;
        seen.add(path);
        const name = (typeof entry.name === "string" && entry.name) || path.split("/").pop() || path;
        const kind = path.startsWith("diagram://")
          ? "diagram"
          : /\.html?$/i.test(path)
            ? "page"
            : OFFICE_FILE.test(path)
              ? "office"
              : "other";
        out.push({ key: path, name, path, kind });
      }
    }
  }
  return out.reverse();
}
