// The state of the knowledge source form: the form itself (prefilled when a link asks for a Git repository), where a
// new repository comes from, the connections and Git candidates, and the custom REST catalog, problems and refusal.
import { useCallback, useEffect, useState } from "react";
import type { FormEvent } from "react";
import { repositoryConnectionOf } from "./connectorConfig";
import type { ConnectorConfig, SourceConnector } from "./connectorTypes";
import { initialForm, resetScope, validate } from "./connectorFormModel";
import type { FormState } from "./connectorFormModel";
import { useGitCandidates } from "./KnowledgeGitConnectionSelect";
import { connectionRepositoriesApi } from "./connectionRepositoriesApi";
import type { RepositoryConnection } from "./connectionRepositoriesApi";
import { requestedAddSource } from "./sourceLinks";
import { useRestCatalog } from "./rest/restSourceApi";
import { REST_KIND } from "./rest/restSourceForm";
import { livePathProblems, restKnowledgeProblems } from "./rest/restSourceRules";
import { restRefusalOf } from "./rest/restSourceRefusals";
import type { Refusal } from "./rest/restSourceRefusals";

// The Bitbucket connections a new Git repository source may be added from; none (or a reader's 403) hides the choice.
function useRepositoryConnections(workspaceId: string | undefined, wanted: boolean): RepositoryConnection[] {
  const [connections, setConnections] = useState<RepositoryConnection[]>([]);
  useEffect(() => {
    if (!workspaceId || !wanted) return undefined;
    let cancelled = false;
    connectionRepositoriesApi.connections(workspaceId)
      .then((answer) => { if (!cancelled) setConnections(answer.connections ?? []); })
      .catch(() => { if (!cancelled) setConnections([]); });
    return () => { cancelled = true; };
  }, [workspaceId, wanted]);
  return connections;
}

type FormInput = {
  editing: SourceConnector | null;
  workspaceId?: string;
  onOwnActions?: (own: boolean) => void;
  isPlatformAdmin: boolean;
  saveRefusal: unknown;
};

export function useConnectorForm({ editing, workspaceId, onOwnActions, isPlatformAdmin, saveRefusal }: FormInput) {
  // A link may open "Add source" on a git repository from a connection (Repositories, a connection's page).
  const asked = editing ? null : requestedAddSource(typeof window === "undefined" ? "" : window.location?.search ?? "");
  const [form, setForm] = useState<FormState>(() => {
    const initial = initialForm(editing);
    return asked?.kind === "git_repository" ? { ...initial, ...resetScope("git_repository") } : initial;
  });
  const [repositoryFrom, setRepositoryFrom] = useState<"url" | "connection">(asked?.fromConnection ? "connection" : "url");
  const connections = useRepositoryConnections(workspaceId, !editing && form.kind === "git_repository");
  const fromConnection = !editing && form.kind === "git_repository" && Boolean(workspaceId) && connections.length > 0
    && repositoryFrom === "connection";
  const [problem, setProblem] = useState<string | null>(null);
  const set = (patch: Partial<FormState>) => setForm((current) => ({ ...current, ...patch }));
  const gitByUrl = form.kind === "git_repository" && !fromConnection;
  const git = useGitCandidates(workspaceId, form.repositoryUrl, gitByUrl, editing?.connection_candidates ?? []);
  const linked = Boolean(editing && repositoryConnectionOf(editing));
  const setConnection = useCallback((connectionId: string) => setForm((current) => ({ ...current, connectionId })), []);
  useEffect(() => { onOwnActions?.(fromConnection); }, [fromConnection, onOwnActions]);
  // Custom REST: its catalog, whether every problem shows (after a save or dry run was tried), and the refusal of the
  // last save or dry run, shown at its field.
  const rest = form.kind === REST_KIND;
  const catalog = useRestCatalog(workspaceId, rest, form.rest.definition);
  const [showRestProblems, setShowRestProblems] = useState(false);
  const [restRefusal, setRestRefusal] = useState<Refusal | null>(null);
  useEffect(() => { if (saveRefusal) setRestRefusal(restRefusalOf(saveRefusal)); }, [saveRefusal]);

  return {
    asked, form, setForm, set, repositoryFrom, setRepositoryFrom, connections, fromConnection, problem, setProblem, gitByUrl, git, linked,
    setConnection, rest, catalog, showRestProblems, setShowRestProblems, restRefusal, setRestRefusal,
  };
}

export type ConnectorFormState = ReturnType<typeof useConnectorForm>;

// What a REST source shows at its fields: every problem once a save or dry run was tried, else the live ones and the
// visibility; the last refusal at its field.
export function restFieldErrors(s: ConnectorFormState, isPlatformAdmin: boolean) {
  const { form, rest, catalog, showRestProblems, restRefusal } = s;
  const restProblems = rest ? restKnowledgeProblems(form.rest, catalog.operations ?? [], isPlatformAdmin) : {};
  const restErrors = rest ? {
    ...(showRestProblems ? restProblems : { ...livePathProblems(form.rest), ...(restProblems["scope.visibility"] ? { "scope.visibility": restProblems["scope.visibility"] } : {}) }),
    ...(restRefusal?.field ? { [restRefusal.field]: restRefusal.text } : {}),
  } : {};
  return { restProblems, restErrors };
}

// The dry run's draft: the REST problems first, then the form's own validation.
export function restDryRunDraft(s: ConnectorFormState, restProblems: Record<string, string>) {
  const { form, setShowRestProblems } = s;
  setShowRestProblems(true);
  if (Object.keys(restProblems).length) return { problem: "Check the highlighted settings first." };
  const checked = validate({ ...form, key: form.key || "draft" });
  return "problem" in checked ? checked : { key: form.key || "draft", config: checked.config };
}

// Validates and saves; a new source empties the form after a successful save.
export async function submitConnectorForm(event: FormEvent, s: ConnectorFormState, { editing, restProblems, onSave }: {
  editing: SourceConnector | null;
  restProblems: Record<string, string>;
  onSave: (connectorKey: string, config: ConnectorConfig) => Promise<boolean>;
}) {
  const { form, setForm, fromConnection, rest, setShowRestProblems, setRestRefusal, setProblem } = s;
  event.preventDefault();
  if (fromConnection) return;
  if (rest) {
    setShowRestProblems(true);
    setRestRefusal(null);
    if (Object.keys(restProblems).length) {
      setProblem("Check the highlighted settings.");
      return;
    }
  }
  const checked = validate(form);
  if ("problem" in checked) {
    setProblem(checked.problem);
    return;
  }
  setProblem(null);
  if (await onSave(form.key, checked.config) && !editing) setForm(initialForm(null));
}
