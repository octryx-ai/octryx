// The Workspace session-episode policy (`projects.config.knowledge_episode_policy`), rendered from what the
// server returns. Each known key is one entry in EPISODE_POLICY_SWITCHES; a key the server returns that this
// table does not know is shown read-only and sent back unchanged on every save (merge semantics).
import { knowledgeBase, request } from "./workspaceKnowledgeRequest";

export type EpisodePolicySwitch = { key: string; label: string; explanation: string };

// Adding a policy switch the server returns (for example `capture_platform_turns`) is one entry here.
export const EPISODE_POLICY_SWITCHES: readonly EpisodePolicySwitch[] = [
  {
    key: "accept_session_episodes",
    label: "Accept session episodes",
    explanation:
      "Platform and CLI sessions of this workspace may return what they learned as a cited episode. Off: every " +
      "episode write is refused with needs_configuration.",
  },
  {
    key: "capture_platform_turns",
    label: "Capture platform turns",
    explanation:
      "At the end of each platform turn, record or update the session's episode automatically (needs Accept " +
      "session episodes).",
  },
];

// Keys of the settings response that describe the Workspace, not the policy. They are never sent back.
export const EPISODE_SETTINGS_ENVELOPE: readonly string[] = ["workspace_id", "may_author", "public_origin_configured"];

export type EpisodeSettings = Record<string, unknown>;

export type EpisodePolicySwitchRow = EpisodePolicySwitch & { value: boolean };
export type EpisodePolicyUnknownRow = { key: string; value: unknown };

export type EpisodePolicyView = {
  switches: EpisodePolicySwitchRow[];
  unknown: EpisodePolicyUnknownRow[];
  mayAuthor: boolean;
  publicOriginConfigured: boolean;
};

function policyEntries(settings: EpisodeSettings): Array<[string, unknown]> {
  return Object.entries(settings).filter(([key]) => !EPISODE_SETTINGS_ENVELOPE.includes(key));
}

// A known key is a switch only when the server returns it as a boolean; anything else is shown as it came.
export function episodePolicyView(settings: EpisodeSettings): EpisodePolicyView {
  const switches: EpisodePolicySwitchRow[] = [];
  const unknown: EpisodePolicyUnknownRow[] = [];
  for (const [key, value] of policyEntries(settings)) {
    const descriptor = EPISODE_POLICY_SWITCHES.find((entry) => entry.key === key);
    if (descriptor && typeof value === "boolean") switches.push({ ...descriptor, value });
    else unknown.push({ key, value });
  }
  switches.sort(
    (a, b) =>
      EPISODE_POLICY_SWITCHES.findIndex((entry) => entry.key === a.key) -
      EPISODE_POLICY_SWITCHES.findIndex((entry) => entry.key === b.key),
  );
  return {
    switches,
    unknown,
    mayAuthor: settings.may_author === true,
    publicOriginConfigured: settings.public_origin_configured === true,
  };
}

// The save body: every policy value the server returned, known or not, with the one change applied.
export function episodePolicyPayload(settings: EpisodeSettings, key: string, value: boolean): EpisodeSettings {
  return { ...Object.fromEntries(policyEntries(settings)), [key]: value };
}

export function describeUnknownValue(value: unknown): string {
  if (value === null || value === undefined) return "not set";
  return typeof value === "string" ? value : JSON.stringify(value);
}

export const episodePolicyApi = {
  get: (workspaceId: string) => request<EpisodeSettings>(`${knowledgeBase(workspaceId)}/episodes/settings`),
  put: (workspaceId: string, body: EpisodeSettings) =>
    request<EpisodeSettings>(`${knowledgeBase(workspaceId)}/episodes/settings`, {
      method: "PUT",
      body: JSON.stringify(body),
    }),
};
