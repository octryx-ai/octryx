// Chat app helpers: activity text, referenced artifacts, chat URLs, draft keys, pill labels.
import type { ChatMessage, ThreadSummary, ToolArtifact } from "../chatThreadTypes";
import type { RuntimeOption } from "../chatOptionTypes";
import { THINKING_LEVEL_LABELS } from "./composer/thinkingSwitch";

export function sanitizeStreamActivityMessage(value: string | null) {
  const text = String(value || "")
    .replace(/\s+/g, " ")
    .trim();
  if (!text) {
    return null;
  }
  const clauses = text
    .split(/(?<=[\.:;!?])\s+/)
    .map((clause) => clause.trim())
    .filter(Boolean);
  const collapsed: string[] = [];
  for (const clause of clauses) {
    const previous = collapsed.at(-1);
    if (previous && previous.toLowerCase() === clause.toLowerCase()) {
      continue;
    }
    collapsed.push(clause);
  }
  const normalized = collapsed.join(" ");
  const lowered = normalized.toLowerCase();
  const transitional = [
    "details",
    "repositories",
    "repositor",
  ].some((marker) => lowered.includes(marker));
  if (transitional) {
    if (lowered.includes("bitbucket")) {
      return "Searching relevant Bitbucket sources…";
    }
    if (lowered.includes("confluence")) {
      return "Searching relevant Confluence pages…";
    }
    if (lowered.includes("jira")) {
      return "Searching relevant Jira tickets…";
    }
    return "Collecting relevant evidence…";
  }
  return normalized.length > 180
    ? `${normalized.slice(0, 177).trimEnd()}…`
    : normalized;
}

export function collectReferencedArtifactsByMessage(messages: ChatMessage[]) {
  const artifactPool: ToolArtifact[] = [];
  const seenArtifactUrls = new Set<string>();
  for (const message of messages) {
    for (const event of message.toolEvents ?? []) {
      for (const artifact of event.artifacts ?? []) {
        if (!artifact?.url || seenArtifactUrls.has(artifact.url)) {
          continue;
        }
        seenArtifactUrls.add(artifact.url);
        artifactPool.push(artifact);
      }
    }
  }

  const mapping = new Map<string, ToolArtifact[]>();
  for (const message of messages) {
    const content = (message.content || "").toLowerCase();
    if (!content) {
      continue;
    }
    const ownArtifactUrls = new Set(
      (message.toolEvents ?? []).flatMap((event) =>
        (event.artifacts ?? []).map((artifact) => artifact.url),
      ),
    );
    const referenced: ToolArtifact[] = [];
    const seenUrls = new Set<string>();
    for (const artifact of artifactPool) {
      if (ownArtifactUrls.has(artifact.url) || seenUrls.has(artifact.url)) {
        continue;
      }
      const needles = [
        artifact.name,
        artifact.path,
        artifact.url,
        artifact.path.split("/").pop() || "",
      ]
        .map((value) => value.trim().toLowerCase())
        .filter(Boolean);
      if (needles.some((needle) => content.includes(needle))) {
        seenUrls.add(artifact.url);
        referenced.push(artifact);
      }
    }
    if (referenced.length) {
      mapping.set(message.id, referenced);
    }
  }
  return mapping;
}

export function buildChatSearch(params: {
  sessionId?: string | null;
  newThread?: boolean;
  projectId?: string;
  runtimeTargetId?: string;
  agentId?: string;
  agentType?: string;
}) {
  const search = new URLSearchParams();
  if (params.sessionId) {
    search.set("session_id", params.sessionId);
  } else if (params.newThread) {
    search.set("new", "true");
  }
  if (!params.sessionId && params.projectId) {
    search.set("project_id", params.projectId);
  }
  if (!params.sessionId && params.runtimeTargetId) {
    search.set("runtime_target_id", params.runtimeTargetId);
  }
  if (!params.sessionId && params.agentId) {
    search.set("agent_id", params.agentId);
  }
  // Keep a fresh thread neutral unless the launch explicitly targets a concrete agent.
  if (
    !params.sessionId &&
    params.agentType &&
    (params.agentId || !params.newThread)
  ) {
    search.set("agent_type", params.agentType);
  }
  const searchString = search.toString();
  return searchString ? `?${searchString}` : "";
}

export function buildComposerDraftKey(params: {
  sessionId?: string | null;
  projectId?: string;
  runtimeTargetId?: string;
  modeKey?: string;
}) {
  if (params.sessionId) {
    return `octryx-chat-draft:${params.sessionId}`;
  }
  return `octryx-chat-draft:new:${params.projectId || "global"}:${params.runtimeTargetId || "auto"}:${params.modeKey || "diagnosis"}`;
}


export function formatRelativeMeta(option: RuntimeOption | undefined) {
  if (!option) {
    return "Auto";
  }
  return option.label;
}

// Quick / Thorough are the person's words for the thinking levels light / deep.
export const THINKING_OPTIONS = [
  { value: "off", label: THINKING_LEVEL_LABELS.off },
  { value: "light", label: THINKING_LEVEL_LABELS.light },
  { value: "deep", label: THINKING_LEVEL_LABELS.deep },
];

export function getRuntimePillLabel(option: RuntimeOption | undefined) {
  if (!option) {
    return "Auto";
  }
  return option.label;
}

export function getProjectPillLabel(projectName: string) {
  return projectName === "No project" ? "Project required" : projectName;
}

export function getThinkingPillLabel(thinkingLevel: string) {
  return (
    THINKING_OPTIONS.find((option) => option.value === thinkingLevel)?.label ||
    THINKING_LEVEL_LABELS.light
  );
}


export function getAgentModeLabel(agentType?: string | null) {
  const normalized = String(agentType || "")
    .trim()
    .toLowerCase();
  if (!normalized) {
    return "Diagnosis";
  }
  return normalized
    .split(/[_\s-]+/)
    .filter(Boolean)
    .map((segment) => segment.charAt(0).toUpperCase() + segment.slice(1))
    .join(" ");
}

export function flattenThreadSearchFields(thread: ThreadSummary): string[] {
  return [
    thread.title,
    thread.preview,
    thread.projectName,
    ...(thread.subThreads ?? []).flatMap((child) =>
      flattenThreadSearchFields(child),
    ),
  ];
}

export function summarizeTaskError(value: string) {
  const firstLine = value
    .split("\n")
    .map((line) => line.trim())
    .find(Boolean);
  if (!firstLine) {
    return "Action failed";
  }
  return firstLine.length > 120 ? `${firstLine.slice(0, 117)}...` : firstLine;
}

export function threadHref(thread: ThreadSummary) {
  return buildChatSearch({ sessionId: thread.id });
}
