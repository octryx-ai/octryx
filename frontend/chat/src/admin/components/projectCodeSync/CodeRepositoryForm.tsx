import type { Dispatch, FormEvent, SetStateAction } from "react";

import { FormSelectField, FormTextField, FormToggleRow, type FieldOption } from "./CodeRepositoryFields";

type CodeRepositoryFormProps = {
  handleSaveProjectCodeRepository: (event: FormEvent) => Promise<void>;
  projectCodeRepositoryName: string;
  setProjectCodeRepositoryName: Dispatch<SetStateAction<string>>;
  projectCodeRepositoryRoot: string;
  setProjectCodeRepositoryRoot: Dispatch<SetStateAction<string>>;
  projectCodeRepositoryProvider: string;
  setProjectCodeRepositoryProvider: Dispatch<SetStateAction<string>>;
  projectCodeRepositoryBranch: string;
  setProjectCodeRepositoryBranch: Dispatch<SetStateAction<string>>;
  projectCodeRepositoryRemoteUrl: string;
  setProjectCodeRepositoryRemoteUrl: Dispatch<SetStateAction<string>>;
  projectCodeRepositoryDescription: string;
  setProjectCodeRepositoryDescription: Dispatch<SetStateAction<string>>;
  projectCodeRepositoryIndexBackend: string;
  setProjectCodeRepositoryIndexBackend: Dispatch<SetStateAction<string>>;
  projectCodeRepositorySemanticBackend: string;
  setProjectCodeRepositorySemanticBackend: Dispatch<SetStateAction<string>>;
  projectCodeRepositoryStructureBackend: string;
  setProjectCodeRepositoryStructureBackend: Dispatch<SetStateAction<string>>;
  projectCodeRepositoryGraphBackend: string;
  setProjectCodeRepositoryGraphBackend: Dispatch<SetStateAction<string>>;
  projectCodeRepositoryActive: boolean;
  setProjectCodeRepositoryActive: Dispatch<SetStateAction<boolean>>;
  projectCodeRepositoryLoading: boolean;
  editingProjectCodeRepositoryId: string | null;
  resetProjectCodeRepositoryForm: () => void;
};

const PROVIDER_OPTIONS: FieldOption[] = [["local", "Local"], ["github", "GitHub"], ["bitbucket", "Bitbucket"]];
const INDEX_OPTIONS: FieldOption[] = [["auto", "Auto"], ["zoekt", "Zoekt"], ["ripgrep", "Ripgrep fallback"]];
const SEMANTIC_OPTIONS: FieldOption[] = [["auto", "Auto"], ["lsp", "LSP"], ["regex", "Regex fallback"]];
const STRUCTURE_OPTIONS: FieldOption[] = [["auto", "Auto"], ["tree-sitter", "Tree-sitter"], ["regex", "Regex fallback"]];
const GRAPH_OPTIONS: FieldOption[] = [["disabled", "Disabled"], ["auto", "Auto"], ["code_graph", "Native graph"]];

function CodeRepositoryFieldGrid(props: CodeRepositoryFormProps) {
  return (
    <div className="admin-form-grid">
      <FormTextField id="project-code-repo-name" label="Repository name" value={props.projectCodeRepositoryName}
        onChange={props.setProjectCodeRepositoryName} placeholder="backend-service" />
      <FormTextField id="project-code-repo-root" label="Repo root" value={props.projectCodeRepositoryRoot}
        onChange={props.setProjectCodeRepositoryRoot} placeholder="/workspace/backend" />
      <FormSelectField id="project-code-repo-provider" label="Provider" value={props.projectCodeRepositoryProvider}
        onChange={props.setProjectCodeRepositoryProvider} options={PROVIDER_OPTIONS} />
      <FormTextField id="project-code-repo-branch" label="Default branch" value={props.projectCodeRepositoryBranch}
        onChange={props.setProjectCodeRepositoryBranch} placeholder="main" />
      <FormTextField id="project-code-repo-remote" label="Remote URL" value={props.projectCodeRepositoryRemoteUrl}
        onChange={props.setProjectCodeRepositoryRemoteUrl} placeholder="https://github.com/org/repo.git" />
      <FormTextField id="project-code-repo-desc" label="Description" value={props.projectCodeRepositoryDescription}
        onChange={props.setProjectCodeRepositoryDescription} placeholder="Primary API codebase" />
      <FormSelectField id="project-code-repo-index" label="Search backend" value={props.projectCodeRepositoryIndexBackend}
        onChange={props.setProjectCodeRepositoryIndexBackend} options={INDEX_OPTIONS} />
      <FormSelectField id="project-code-repo-semantic" label="Semantic backend"
        value={props.projectCodeRepositorySemanticBackend} onChange={props.setProjectCodeRepositorySemanticBackend}
        options={SEMANTIC_OPTIONS} />
      <FormSelectField id="project-code-repo-structure" label="Structure backend"
        value={props.projectCodeRepositoryStructureBackend} onChange={props.setProjectCodeRepositoryStructureBackend}
        options={STRUCTURE_OPTIONS} />
      <FormSelectField id="project-code-repo-graph" label="Graph backend" value={props.projectCodeRepositoryGraphBackend}
        onChange={props.setProjectCodeRepositoryGraphBackend} options={GRAPH_OPTIONS} />
    </div>
  );
}

export function CodeRepositoryForm(props: CodeRepositoryFormProps) {
  const {
    handleSaveProjectCodeRepository,
    projectCodeRepositoryActive,
    setProjectCodeRepositoryActive,
    projectCodeRepositoryLoading,
    editingProjectCodeRepositoryId,
    resetProjectCodeRepositoryForm,
  } = props;
  return (
    <form
      className="admin-modal__stack"
      onSubmit={(e) => void handleSaveProjectCodeRepository(e)}
    >
      <CodeRepositoryFieldGrid {...props} />
      <FormToggleRow
        on={projectCodeRepositoryActive}
        title={projectCodeRepositoryActive ? "Repository active" : "Repository inactive"}
        text="Inactive repositories stay configured but are ignored for operational indexing."
        ariaLabel="Toggle code repository activity"
        onToggle={() => setProjectCodeRepositoryActive((value) => !value)}
      />
      <div className="admin-form-help">
        Recommended production path: Zoekt for search, Tree-sitter for
        structure and the native code graph for context.
      </div>
      <div className="admin-panel__form-actions">
        <button
          type="submit"
          className="admin-panel__action-btn admin-panel__action-btn--primary"
          disabled={projectCodeRepositoryLoading}
        >
          {projectCodeRepositoryLoading
            ? "Saving…"
            : editingProjectCodeRepositoryId
              ? "Save Code Repository"
              : "Add Code Repository"}
        </button>
        {editingProjectCodeRepositoryId && (
          <button
            type="button"
            className="admin-panel__action-btn"
            onClick={() => resetProjectCodeRepositoryForm()}
          >
            Cancel Edit
          </button>
        )}
      </div>
    </form>
  );
}
