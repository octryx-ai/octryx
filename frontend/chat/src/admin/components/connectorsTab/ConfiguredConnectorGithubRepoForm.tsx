import type { CSSProperties, ReactNode } from "react";

type ConfiguredConnectorGithubRepoFormProps = {
  connector: any;
  ctx: Record<string, unknown>;
};

type RepoForm = Record<string, any>;
type SetRepoForm = (update: (prev: any) => any) => void;
type Choice = { value: string; label: string };

const OWNER_TYPES: Choice[] = [
  { value: "org", label: "Organization" },
  { value: "user", label: "User" },
];
const VISIBILITIES: Choice[] = [
  { value: "private", label: "Private" },
  { value: "public", label: "Public" },
];
const INDEX_BACKENDS: Choice[] = [
  { value: "auto", label: "Auto" },
  { value: "zoekt", label: "Zoekt" },
  { value: "ripgrep", label: "Ripgrep" },
];
const SEMANTIC_BACKENDS: Choice[] = [
  { value: "auto", label: "Auto" },
  { value: "lsp", label: "LSP" },
  { value: "regex", label: "Regex" },
];
const STRUCTURE_BACKENDS: Choice[] = [
  { value: "auto", label: "Auto" },
  { value: "tree-sitter", label: "Tree-sitter" },
  { value: "regex", label: "Regex" },
];
const GRAPH_BACKENDS: Choice[] = [
  { value: "auto", label: "Auto" },
  { value: "code_graph", label: "Native graph" },
  { value: "disabled", label: "Disabled" },
];
// The options above the code-repository registration, in display order.
const CHECKBOXES: Array<{ field: string; label: string }> = [
  { field: "create_readme", label: "Create README" },
  { field: "create_gitignore", label: "Create .gitignore" },
  { field: "initial_commit", label: "Initial commit" },
  { field: "register_code_repository", label: "Register as code repository" },
];

type FieldProps = { form: RepoForm; setForm: SetRepoForm; field: string; label: string };

function RepoTextField({ form, setForm, field, label, placeholder, style }: FieldProps & { placeholder: string; style?: CSSProperties }) {
  return (
    <div className="connector-field" style={style}>
      <label className="connector-field__label">{label}</label>
      <input
        className="connector-field__input"
        value={form[field]}
        onChange={(e) =>
          setForm((prev: any) => ({
            ...prev,
            [field]: e.target.value,
          }))
        }
        placeholder={placeholder}
      />
    </div>
  );
}

function RepoSelectField({ form, setForm, field, label, choices, children }: FieldProps & { choices: Choice[]; children?: ReactNode }) {
  return (
    <div className="connector-field">
      <label className="connector-field__label">{label}</label>
      <select
        className="connector-field__input"
        value={form[field]}
        onChange={(e) =>
          setForm((prev: any) => ({
            ...prev,
            [field]: e.target.value,
          }))
        }
      >
        {children}
        {choices.map((choice) => (
          <option key={choice.value} value={choice.value}>{choice.label}</option>
        ))}
      </select>
    </div>
  );
}

function RepoCheckbox({ form, setForm, field, label }: FieldProps) {
  return (
    <label className="connector-field connector-field--checkbox">
      <input
        type="checkbox"
        checked={form[field]}
        onChange={(e) =>
          setForm((prev: any) => ({
            ...prev,
            [field]: e.target.checked,
          }))
        }
      />
      <span>{label}</span>
    </label>
  );
}

function RepoBasicsFields({ form, setForm, ownerPlaceholder }: { form: RepoForm; setForm: SetRepoForm; ownerPlaceholder: string }) {
  const shared = { form, setForm };
  return (
    <div className="connector-card__fields">
      <RepoTextField {...shared} field="name" label="Repository name" placeholder="platform-api" />
      <RepoTextField {...shared} field="owner" label="Owner override" placeholder={ownerPlaceholder} />
      <RepoSelectField {...shared} field="owner_type" label="Owner type" choices={OWNER_TYPES} />
      <RepoSelectField {...shared} field="visibility" label="Visibility" choices={VISIBILITIES} />
      <RepoTextField {...shared} field="default_branch" label="Default branch" placeholder="main" />
      <RepoTextField {...shared} field="local_path" label="Local bootstrap path" placeholder="/workspace/repos/platform-api" />
      <RepoTextField {...shared} field="description" label="Description" placeholder="Primary service repository"
        style={{ gridColumn: "1 / -1" }} />
    </div>
  );
}

function RepoCodeRepositoryFields({ form, setForm, projects }: { form: RepoForm; setForm: SetRepoForm; projects: any[] }) {
  const shared = { form, setForm };
  return (
    <div className="connector-card__fields">
      <RepoSelectField {...shared} field="project_id" label="Project"
        choices={projects.map((project: any) => ({ value: project.id, label: project.name }))}>
        <option value="">Select project</option>
      </RepoSelectField>
      <RepoSelectField {...shared} field="index_backend" label="Search backend" choices={INDEX_BACKENDS} />
      <RepoSelectField {...shared} field="semantic_backend" label="Semantic backend" choices={SEMANTIC_BACKENDS} />
      <RepoSelectField {...shared} field="structure_backend" label="Structure backend" choices={STRUCTURE_BACKENDS} />
      <RepoSelectField {...shared} field="graph_backend" label="Graph backend" choices={GRAPH_BACKENDS} />
    </div>
  );
}

export function ConfiguredConnectorGithubRepoForm({
  connector,
  ctx,
}: ConfiguredConnectorGithubRepoFormProps) {
  const {
    githubConnectorRepoCreateLoading,
    githubConnectorRepoForm,
    handleCreateGithubConnectorRepository,
    projects,
    setGithubConnectorRepoForm,
  } = ctx as Record<string, any>;
  const shared = { form: githubConnectorRepoForm, setForm: setGithubConnectorRepoForm };

  return (
    <>
      <div className="connector-card__tools-label">Create repository</div>
      <RepoBasicsFields {...shared} ownerPlaceholder={String(connector.public_fields.github_owner || "owner")} />

      <div
        className="admin-inline-actions"
        style={{ marginTop: 8, marginBottom: 8, flexWrap: "wrap" }}
      >
        {CHECKBOXES.map((box) => <RepoCheckbox key={box.field} {...shared} field={box.field} label={box.label} />)}
      </div>

      {githubConnectorRepoForm.register_code_repository ? (
        <RepoCodeRepositoryFields {...shared} projects={projects} />
      ) : null}

      <div className="connector-card__actions">
        <button
          type="button"
          className="admin-panel__action-btn admin-panel__action-btn--primary"
          disabled={
            !connector.configured ||
            githubConnectorRepoCreateLoading ||
            !githubConnectorRepoForm.name.trim()
          }
          onClick={() => void handleCreateGithubConnectorRepository()}
        >
          {githubConnectorRepoCreateLoading ? "Creating…" : "Create repository"}
        </button>
      </div>
    </>
  );
}
