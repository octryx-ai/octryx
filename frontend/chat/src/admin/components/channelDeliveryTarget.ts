// Readable view of a Teams delivery target. The stored value keeps
// the backend's pipe format (services/admin/connector/admin_channel_service.py
// _is_supported_teams_target); this only explains its parts before saving.

export const TEAMS_TARGET_EXAMPLES = [
  {
    kind: "Existing conversation",
    format: "serviceUrl|conversationId",
    example: "https://smba.trafficmanager.net/emea/|19:abc123@thread.tacv2",
  },
  {
    kind: "New channel thread per delivery",
    format: "thread|serviceUrl|tenantId|teamId|channelId",
    example:
      "thread|https://smba.trafficmanager.net/emea/|<tenant-id>|<team-id>|19:channel@thread.tacv2",
  },
] as const;

export type TeamsTargetPart = { label: string; value: string };

export type TeamsTargetDescription =
  | { state: "empty" }
  | { state: "valid"; kind: string; parts: TeamsTargetPart[] }
  | { state: "invalid"; message: string };

const THREAD_LABELS = ["Service URL", "Tenant ID", "Team ID", "Channel ID"];

export function describeTeamsTarget(raw: string): TeamsTargetDescription {
  const target = raw.trim();
  if (!target) return { state: "empty" };
  if (target.startsWith("thread|")) {
    const parts = target.split("|").slice(1);
    if (parts.length !== 4 || parts.some((part) => !part.trim())) {
      return {
        state: "invalid",
        message: "A new channel thread needs five parts: thread|serviceUrl|tenantId|teamId|channelId.",
      };
    }
    return {
      state: "valid",
      kind: TEAMS_TARGET_EXAMPLES[1].kind,
      parts: parts.map((value, index) => ({ label: THREAD_LABELS[index], value: value.trim() })),
    };
  }
  const separator = target.indexOf("|");
  const serviceUrl = separator >= 0 ? target.slice(0, separator).trim() : "";
  const conversationId = separator >= 0 ? target.slice(separator + 1).trim() : "";
  if (!serviceUrl || !conversationId) {
    return {
      state: "invalid",
      message: "An existing conversation needs two parts: serviceUrl|conversationId.",
    };
  }
  return {
    state: "valid",
    kind: TEAMS_TARGET_EXAMPLES[0].kind,
    parts: [
      { label: "Service URL", value: serviceUrl },
      { label: "Conversation ID", value: conversationId },
    ],
  };
}
