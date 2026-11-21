import { useEffect, useState } from "react";
import { connectorRequest } from "../connectorsApi";
import { knowledgeBase } from "../workspaceKnowledgeRequest";
import { restCatalogOf } from "./restSourceRules";
import { restRefusalOf } from "./restSourceRefusals";
import type { RestApiChoice } from "./restSourceRules";
import type { RestOperationInfo } from "../../../../chat/work/intake/restIntakeForm";

// What a REST Knowledge source can read (`GET …/knowledge/rest-sources`): the REST APIs this Workspace reaches
// and their enabled read operations with the roles their grants name. A Workspace owner or admin may read it without
// Secure Work access; it never carries servers, auth or credentials.

export type RestCatalog = {
  apis: RestApiChoice[] | null;
  operations: RestOperationInfo[] | null;
  apiName: string;
  problem: string | null;
};

export const restSourceApi = {
  catalog: (workspaceId: string) => connectorRequest<unknown>(`${knowledgeBase(workspaceId)}/rest-sources`),
};

export function useRestCatalog(workspaceId: string | undefined, wanted: boolean, definition: string): RestCatalog {
  const [apis, setApis] = useState<RestApiChoice[] | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  useEffect(() => {
    if (!workspaceId || !wanted) return undefined;
    let active = true;
    restSourceApi.catalog(workspaceId)
      .then((answer) => { if (active) setApis(restCatalogOf(answer)); })
      .catch((error: unknown) => {
        if (!active) return;
        setApis([]);
        setProblem(`The REST APIs could not be read. ${restRefusalOf(error).text}`);
      });
    return () => { active = false; };
  }, [workspaceId, wanted]);
  const api = definition && apis ? apis.find((entry) => entry.id === definition) ?? null : null;
  return {
    apis,
    // A stored source whose API is no longer offered: no operation to pick, the save names it at its field.
    operations: !definition ? [] : apis ? api?.operations ?? [] : null,
    apiName: api?.name ?? definition,
    problem,
  };
}
