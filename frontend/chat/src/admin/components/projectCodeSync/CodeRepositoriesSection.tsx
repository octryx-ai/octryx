import type { AdminProjectCodeSyncSectionProps } from "../AdminProjectCodeSyncSection.types";
import { CodeRepositoryCard } from "./CodeRepositoryCard";
import { CodeRepositoryForm } from "./CodeRepositoryForm";

type CodeRepositoriesSectionProps = {
  props: AdminProjectCodeSyncSectionProps;
};

// What the repository form reads and writes: the fields of the repository being added or edited, and the save.
const FORM_KEYS = [
  "handleSaveProjectCodeRepository",
  "projectCodeRepositoryName",
  "setProjectCodeRepositoryName",
  "projectCodeRepositoryRoot",
  "setProjectCodeRepositoryRoot",
  "projectCodeRepositoryProvider",
  "setProjectCodeRepositoryProvider",
  "projectCodeRepositoryBranch",
  "setProjectCodeRepositoryBranch",
  "projectCodeRepositoryRemoteUrl",
  "setProjectCodeRepositoryRemoteUrl",
  "projectCodeRepositoryDescription",
  "setProjectCodeRepositoryDescription",
  "projectCodeRepositoryIndexBackend",
  "setProjectCodeRepositoryIndexBackend",
  "projectCodeRepositorySemanticBackend",
  "setProjectCodeRepositorySemanticBackend",
  "projectCodeRepositoryStructureBackend",
  "setProjectCodeRepositoryStructureBackend",
  "projectCodeRepositoryGraphBackend",
  "setProjectCodeRepositoryGraphBackend",
  "projectCodeRepositoryActive",
  "setProjectCodeRepositoryActive",
  "projectCodeRepositoryLoading",
  "editingProjectCodeRepositoryId",
  "resetProjectCodeRepositoryForm",
] as const;

type FormProps = Pick<AdminProjectCodeSyncSectionProps, (typeof FORM_KEYS)[number]>;

const formProps = (props: AdminProjectCodeSyncSectionProps) =>
  Object.fromEntries(FORM_KEYS.map((key) => [key, props[key]])) as FormProps;

export function CodeRepositoriesSection({
  props,
}: CodeRepositoriesSectionProps) {
  const {
    configuringProjectQuality,
    handleDeleteProjectCodeRepository,
    handleEditProjectCodeRepository,
    handleRunProjectCodeIndex,
    projectCodeRepositoryLoading,
    projectCodeRepositoryRunningId,
  } = props;

  return (
    <section className="admin-modal__stack" style={{ marginTop: 20 }}>
      <div className="admin-panel__section-header">
        <span>
          Code Intelligence Repositories (
          {(configuringProjectQuality.code_repositories || []).length})
        </span>
      </div>
      <p className="admin-panel__hint">
        Register coding repositories per project and choose how search, semantic
        lookup, structure parsing and optional graph context should run.
      </p>
      <div className="connector-grid">
        {(configuringProjectQuality.code_repositories || []).map((repo) => (
          <CodeRepositoryCard
            key={repo.id}
            repo={repo}
            projectCodeRepositoryRunningId={projectCodeRepositoryRunningId}
            projectCodeRepositoryLoading={projectCodeRepositoryLoading}
            handleEditProjectCodeRepository={handleEditProjectCodeRepository}
            handleRunProjectCodeIndex={handleRunProjectCodeIndex}
            handleDeleteProjectCodeRepository={
              handleDeleteProjectCodeRepository
            }
          />
        ))}
      </div>
      <CodeRepositoryForm {...formProps(props)} />
    </section>
  );
}
