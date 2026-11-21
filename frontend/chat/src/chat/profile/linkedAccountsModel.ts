// Linked accounts: a user's accounts on Atlassian Cloud, Jira/Bitbucket Server,
// GitHub and GitLab — the one home reviewer, author and assignee resolution reads (backend
// api/routes/linked_accounts.py). Pure parsing and presentation; the panel renders it.

export type IdentifierKind = "account_id" | "username";
export type VerificationStatus = "unverified" | "verified" | "failed";

export type LinkedPlatform = {
  platform: string;
  label: string;
  identifierKind: IdentifierKind;
  description: string;
};

export type LinkedAccount = {
  platform: string;
  label: string;
  identifier: string;
  displayName: string | null;
  verificationStatus: VerificationStatus;
  verifiedAt: string | null;
  verificationDetail: string;
  source: string;
};

export type LinkedAccounts = {
  user: { id: string; username: string; displayName: string | null };
  accounts: LinkedAccount[];
  platforms: LinkedPlatform[];
  workspaces: { id: string; name: string }[];
};

const ATLASSIAN = "atlassian";

function text(value: unknown): string {
  return typeof value === "string" ? value : "";
}

function record(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value) ? (value as Record<string, unknown>) : {};
}

function status(value: unknown): VerificationStatus {
  return value === "verified" || value === "failed" ? value : "unverified";
}

export function readLinkedAccount(value: unknown): LinkedAccount | null {
  const raw = record(value);
  const platform = text(raw.platform);
  if (!platform) return null;
  return {
    platform,
    label: text(raw.label) || platform,
    identifier: text(raw.identifier),
    displayName: text(raw.display_name) || null,
    verificationStatus: status(raw.verification_status),
    verifiedAt: text(raw.verified_at) || null,
    verificationDetail: text(record(raw.verification).detail),
    source: text(raw.source),
  };
}

export function readLinkedAccounts(value: unknown): LinkedAccounts | null {
  const raw = record(value);
  if (!Array.isArray(raw.accounts) || !Array.isArray(raw.platforms)) return null;
  const user = record(raw.user);
  return {
    user: { id: text(user.id), username: text(user.username), displayName: text(user.display_name) || null },
    accounts: raw.accounts.map(readLinkedAccount).filter((item): item is LinkedAccount => item !== null),
    platforms: raw.platforms
      .map((item) => record(item))
      .filter((item) => text(item.platform))
      .map((item) => ({
        platform: text(item.platform),
        label: text(item.label) || text(item.platform),
        identifierKind: item.identifier_kind === "account_id" ? "account_id" : "username",
        description: text(item.description),
      })),
    workspaces: (Array.isArray(raw.workspaces) ? raw.workspaces : [])
      .map((item) => record(item))
      .filter((item) => text(item.id))
      .map((item) => ({ id: text(item.id), name: text(item.name) || text(item.id) })),
  };
}

/** One row per platform: the linked account, or none yet. */
export function platformRows(data: LinkedAccounts): { platform: LinkedPlatform; account: LinkedAccount | null }[] {
  return data.platforms.map((platform) => ({
    platform,
    account: data.accounts.find((account) => account.platform === platform.platform) ?? null,
  }));
}

export function identifierLabel(kind: IdentifierKind): string {
  return kind === "account_id" ? "Account id" : "Username";
}

/** Whether a Workspace connection can check accounts of this platform (GitHub and GitLab offer no lookup). */
export function canVerify(platform: string): boolean {
  return platform === ATLASSIAN || platform === "jira_server" || platform === "bitbucket_server";
}

/** Only an Atlassian account is found by its email (through the Workspace's Jira Cloud connection). */
export function canFindByEmail(platform: string): boolean {
  return platform === ATLASSIAN;
}

export function verificationBadge(account: LinkedAccount): { label: string; tone: string } {
  if (account.verificationStatus === "verified") return { label: "Verified", tone: "active" };
  if (account.verificationStatus === "failed") return { label: "Not found", tone: "danger" };
  return { label: "Unverified", tone: "attention" };
}

const REASONS: Record<string, string> = {
  not_your_account: "You can change only your own linked accounts.",
  invalid_account_id: "This is not an Atlassian account id.",
  invalid_username: "A username has no spaces or slashes.",
  workspace_required: "Choose the Workspace whose connection checks the account.",
  project_not_found: "This Workspace does not exist, or you are not a member of it.",
  needs_configuration: "This Workspace has no connection that can check this account.",
  not_verifiable: "This platform's connection offers no account lookup; the account is used as entered.",
  account_not_found: "No single Atlassian account shows this email.",
  not_linked: "Link the account before checking it.",
};

export type LinkedAccountRequestError = Error & { status: number; code: string | null; detail: string | null };

export function linkedAccountErrorText(error: unknown): string {
  const failure = error as Partial<LinkedAccountRequestError> | null;
  if (failure?.code && REASONS[failure.code]) {
    return failure.code === "needs_configuration" && failure.detail ? failure.detail : REASONS[failure.code];
  }
  return "The linked account could not be saved.";
}

/** Where the requester links their account from a run card ("Link your account to be added as reviewer"). */
export const LINK_ACCOUNT_HREF = "/chat?area=personal&tab=profile";
