import { connectorRequest } from "../connectorsApi";
import { knowledgeBase } from "../workspaceKnowledgeRequest";
import { sourceAclBody } from "./sourceAclModel";

// `GET|PUT …/knowledge/source-acl` (platform admin). Refusals arrive as ConnectorRequestError (status, code).
export const sourceAclApi = {
  get: (workspaceId: string) => connectorRequest<unknown>(`${knowledgeBase(workspaceId)}/source-acl`),
  put: (workspaceId: string, enforce: boolean, reason: string, dryRun: boolean) =>
    connectorRequest<unknown>(`${knowledgeBase(workspaceId)}/source-acl`, {
      method: "PUT",
      body: JSON.stringify(sourceAclBody(enforce, reason, dryRun)),
    }),
};
