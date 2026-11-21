// Who sees what on Knowledge › Sources. Presentation only: every call keeps the server's check.
//
// - the page: platform admins, and admins/owners of the Workspace in focus (the nav entry is `workspaceAdmin`, the
//   same rule as Operations › Costs); a member reaches it only by a link and sees the sources read-only.
// - sources: whoever the listing's `may_author` admits (Workspace admin/owner) adds, edits and runs them, of every kind
//   the server lets an author configure; "workspace" visibility of a REST source stays a platform admin's (403).
// - the source-permissions switch: read and changed by a platform admin only (its GET is admin-only too), so it is
//   hidden for everyone else, and the held-back notice tells them to ask a platform admin.

export type KnowledgeSourcesAccess = {
  workspaceVisibility: boolean;
  aclSwitch: boolean;
  // How the held-back notice ends: a link to the switch, or whom to ask.
  aclNotice: "link" | "ask";
};

export function knowledgeSourcesAccess(isPlatformAdmin: boolean): KnowledgeSourcesAccess {
  return { workspaceVisibility: isPlatformAdmin, aclSwitch: isPlatformAdmin, aclNotice: isPlatformAdmin ? "link" : "ask" };
}

export const ACL_NOTICE_LINK = "Enforce source permissions in this Workspace";
export const ACL_NOTICE_ASK = "Ask a platform admin to enforce source permissions in this Workspace.";
