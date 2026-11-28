// Presentation only, every call keeps the server's check: the source-permissions switch GET is platform-admin only, so the switch is hidden for everyone else.

export type KnowledgeSourcesAccess = {
  workspaceVisibility: boolean;
  aclSwitch: boolean;
  aclNotice: "link" | "ask";
};

export function knowledgeSourcesAccess(isPlatformAdmin: boolean): KnowledgeSourcesAccess {
  return { workspaceVisibility: isPlatformAdmin, aclSwitch: isPlatformAdmin, aclNotice: isPlatformAdmin ? "link" : "ask" };
}

export const ACL_NOTICE_LINK = "Enforce source permissions in this Workspace";
export const ACL_NOTICE_ASK = "Ask a platform admin to enforce source permissions in this Workspace.";
