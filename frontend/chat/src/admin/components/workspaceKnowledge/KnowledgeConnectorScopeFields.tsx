import { SERVICENOW_TABLES, spaceKeyFromUrl } from "./connectorFormModel";
import type { FormState, ServiceNowTable } from "./connectorFormModel";
import { KnowledgeGitRepositoryFields } from "./KnowledgeGitRepositoryFields";
import { KnowledgeConfluenceScopeFields } from "./KnowledgeConfluenceScopeFields";
import { KnowledgeFormField } from "./KnowledgeFormField";

const TABLE_LABEL: Record<ServiceNowTable, string> = { incident: "Incidents", problem: "Problems" };
const CHECKBOX_LABEL = { display: "flex", alignItems: "center", gap: "0.35rem" } as const;

type Props = { form: FormState; set: (patch: Partial<FormState>) => void };

// ServiceNow: knowledge base articles and incident/problem records, each narrowed by an optional encoded query.
function ServiceNowFields({ form, set }: Props) {
  const toggleTable = (table: ServiceNowTable, checked: boolean) =>
    set({ tables: checked ? [...form.tables.filter((item) => item !== table), table] : form.tables.filter((item) => item !== table) });
  return (
    <>
      <KnowledgeFormField label="Knowledge bases (sys_ids, comma separated)">
        <input className="admin-panel__input" aria-label="Knowledge bases" value={form.knowledgeBases}
          placeholder="Knowledge base sys_ids (optional), comma separated"
          onChange={(event) => set({ knowledgeBases: event.target.value })} />
      </KnowledgeFormField>
      <KnowledgeFormField label="Article filter">
        <input className="admin-panel__input" aria-label="Article filter" value={form.articleQuery}
          disabled={!form.knowledgeBases.trim()}
          placeholder="Optional article filter (encoded query), e.g. kb_category=0f1e…^short_descriptionLIKEfailover"
          onChange={(event) => set({ articleQuery: event.target.value })} />
      </KnowledgeFormField>
      <div style={{ display: "flex", flexWrap: "wrap", gap: "1rem", alignItems: "center" }}>
        <span className="admin-panel__muted">Record tables</span>
        {SERVICENOW_TABLES.map((table) => (
          <label key={table} className="admin-panel__muted" style={CHECKBOX_LABEL}>
            <input type="checkbox" checked={form.tables.includes(table)}
              onChange={(event) => toggleTable(table, event.target.checked)} />
            {TABLE_LABEL[table]} (<code>{table}</code>)
          </label>
        ))}
      </div>
      <KnowledgeFormField label="Record filter">
        <input className="admin-panel__input" aria-label="Record filter" value={form.recordQuery}
          disabled={!form.tables.length}
          placeholder="Optional record filter (encoded query), e.g. state=7^assignment_group=a1b2…"
          onChange={(event) => set({ recordQuery: event.target.value })} />
      </KnowledgeFormField>
    </>
  );
}

// The key inside a pasted page address. Where a space key comes from in general is in the page help
// (help/knowledge/knowledgeSources.md; the form has no explanatory text); only a pasted address is answered here.
function SpaceKeyHelp({ keys }: { keys: string }) {
  const pasted = keys.split(/[\s,]+/).map((item) => ({ item, key: spaceKeyFromUrl(item) })).find((entry) => entry.key);
  if (!pasted) return null;
  return (
    <div className="admin-panel__hint" style={{ margin: 0 }} data-testid="space-key-help">
      The pasted address belongs to the space <code>{pasted.key}</code>; enter that key instead.
    </div>
  );
}

// The kind-specific scope inputs: whole spaces or page trees (Confluence), project keys and JQL (Jira), the ServiceNow scope, or the
// Git repository, ref, globs and limits.
// Kubernetes: one cluster (bound by a named connection) and optionally some of its namespaces.
function KubernetesFields({ form, set }: Props) {
  return (
    <>
      <KnowledgeFormField label="Cluster">
        <input className="admin-panel__input" aria-label="Cluster" value={form.cluster}
          placeholder="Cluster (the name a Kubernetes connection is bound to)"
          onChange={(event) => set({ cluster: event.target.value })} />
      </KnowledgeFormField>
      <KnowledgeFormField label="Namespaces">
        <input className="admin-panel__input" aria-label="Namespaces" value={form.namespaces}
          placeholder="Optional namespaces, comma separated (empty: every namespace the connection may read)"
          onChange={(event) => set({ namespaces: event.target.value })} />
      </KnowledgeFormField>
    </>
  );
}

export function KnowledgeConnectorScopeFields({ form, set, lockedUrl = false, urlProblem = null }: Props & {
  lockedUrl?: boolean; urlProblem?: string | null;
}) {
  if (form.kind === "servicenow") return <ServiceNowFields form={form} set={set} />;
  if (form.kind === "kubernetes") return <KubernetesFields form={form} set={set} />;
  if (form.kind === "git_repository") return <KnowledgeGitRepositoryFields form={form} set={set} lockedUrl={lockedUrl} urlProblem={urlProblem} />;
  const jira = form.kind === "jira";
  const keysInput = (
    <KnowledgeFormField label={jira ? "Project keys" : "Space keys"}>
      <input className="admin-panel__input" aria-label={jira ? "Project keys" : "Space keys"}
        placeholder={jira ? "Project keys: PROJ1, PROJ2" : "Space keys: SPACE1, SPACE2"}
        value={form.keys} onChange={(event) => set({ keys: event.target.value })} />
    </KnowledgeFormField>
  );
  if (!jira) {
    return (
      <KnowledgeConfluenceScopeFields form={form} set={set}
        spaceKeysInput={<>{keysInput}<SpaceKeyHelp keys={form.keys} /></>} />
    );
  }
  return (
    <>
      {keysInput}
      <KnowledgeFormField label="JQL filter">
        <input className="admin-panel__input" aria-label="JQL filter" value={form.jql}
          placeholder="Optional JQL filter, e.g. status = Done AND labels = runbook"
          onChange={(event) => set({ jql: event.target.value })} />
      </KnowledgeFormField>
    </>
  );
}
