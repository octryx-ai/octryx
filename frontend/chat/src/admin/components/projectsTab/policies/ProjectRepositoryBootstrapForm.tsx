import type { FormEvent } from "react";

import {
  FormSelectField,
  FormTextField,
  FormToggleRow,
  type FieldOption,
} from "../../projectCodeSync/CodeRepositoryFields";

type ProjectRepositoryBootstrapFormProps = {
  projectRepoBootstrapProvider: string;
  setProjectRepoBootstrapProvider: (value: string) => void;
  projectRepoBootstrapDefaultBranch: string;
  setProjectRepoBootstrapDefaultBranch: (value: string) => void;
  projectRepoBootstrapDefaultRepoName: string;
  setProjectRepoBootstrapDefaultRepoName: (value: string) => void;
  projectRepoBootstrapWorkspaceSubdir: string;
  setProjectRepoBootstrapWorkspaceSubdir: (value: string) => void;
  projectRepoBootstrapRemoteVisibility: string;
  setProjectRepoBootstrapRemoteVisibility: (value: string) => void;
  projectRepoBootstrapGithubOwner: string;
  setProjectRepoBootstrapGithubOwner: (value: string) => void;
  projectRepoBootstrapGithubOwnerType: string;
  setProjectRepoBootstrapGithubOwnerType: (value: string) => void;
  projectRepoBootstrapBitbucketProjectKey: string;
  setProjectRepoBootstrapBitbucketProjectKey: (value: string) => void;
  projectRepoBootstrapEnabled: boolean;
  setProjectRepoBootstrapEnabled: (
    value: boolean | ((prev: boolean) => boolean),
  ) => void;
  projectRepoBootstrapAutoOnSessionStart: boolean;
  setProjectRepoBootstrapAutoOnSessionStart: (
    value: boolean | ((prev: boolean) => boolean),
  ) => void;
  projectQualityLoading: boolean;
  onSubmit: (event: FormEvent<HTMLFormElement>) => void | Promise<void>;
  onUseImplicitLocalFallback: () => void | Promise<void>;
};

type Props = ProjectRepositoryBootstrapFormProps;

const PROVIDER_OPTIONS: FieldOption[] = [
  ["local", "Local repository"],
  ["github", "GitHub repository"],
  ["bitbucket", "Bitbucket repository"],
];
const VISIBILITY_OPTIONS: FieldOption[] = [["private", "Private"], ["public", "Public"]];
const OWNER_TYPE_OPTIONS: FieldOption[] = [["org", "Organization"], ["user", "User"]];

function BootstrapProviderFields(props: Props) {
  if (props.projectRepoBootstrapProvider === "github") {
    return (
      <>
        <FormTextField id="project-repo-bootstrap-github-owner" label="GitHub owner"
          value={props.projectRepoBootstrapGithubOwner} onChange={props.setProjectRepoBootstrapGithubOwner}
          placeholder="owner" />
        <FormSelectField id="project-repo-bootstrap-github-owner-type" label="GitHub owner type"
          value={props.projectRepoBootstrapGithubOwnerType} onChange={props.setProjectRepoBootstrapGithubOwnerType}
          options={OWNER_TYPE_OPTIONS} />
      </>
    );
  }
  if (props.projectRepoBootstrapProvider === "bitbucket") {
    return (
      <FormTextField id="project-repo-bootstrap-bitbucket-project" label="Bitbucket project key"
        value={props.projectRepoBootstrapBitbucketProjectKey} onChange={props.setProjectRepoBootstrapBitbucketProjectKey}
        placeholder="PROJ" />
    );
  }
  return null;
}

function BootstrapFieldGrid(props: Props) {
  return (
    <div className="admin-form-grid">
      <FormSelectField id="project-repo-bootstrap-provider" label="Provider" value={props.projectRepoBootstrapProvider}
        onChange={props.setProjectRepoBootstrapProvider} options={PROVIDER_OPTIONS} />
      <FormTextField id="project-repo-bootstrap-branch" label="Default branch"
        value={props.projectRepoBootstrapDefaultBranch} onChange={props.setProjectRepoBootstrapDefaultBranch}
        placeholder="main" />
      <FormTextField id="project-repo-bootstrap-name" label="Default repo name"
        value={props.projectRepoBootstrapDefaultRepoName} onChange={props.setProjectRepoBootstrapDefaultRepoName}
        placeholder="service-x" />
      <FormTextField id="project-repo-bootstrap-subdir" label="Project checkout subdir"
        value={props.projectRepoBootstrapWorkspaceSubdir} onChange={props.setProjectRepoBootstrapWorkspaceSubdir}
        placeholder="repo" />
      <FormSelectField id="project-repo-bootstrap-visibility" label="Remote visibility"
        value={props.projectRepoBootstrapRemoteVisibility} onChange={props.setProjectRepoBootstrapRemoteVisibility}
        options={VISIBILITY_OPTIONS} />
      <BootstrapProviderFields {...props} />
    </div>
  );
}

export function ProjectRepositoryBootstrapForm(props: Props) {
  const {
    projectRepoBootstrapEnabled,
    setProjectRepoBootstrapEnabled,
    projectRepoBootstrapAutoOnSessionStart,
    setProjectRepoBootstrapAutoOnSessionStart,
    projectQualityLoading,
    onSubmit,
    onUseImplicitLocalFallback,
  } = props;
  return (
    <form
      className="admin-modal__stack"
      style={{ marginTop: 20 }}
      onSubmit={(event) => void onSubmit(event)}
    >
      <BootstrapFieldGrid {...props} />
      <FormToggleRow
        on={projectRepoBootstrapEnabled}
        title={projectRepoBootstrapEnabled ? "Bootstrap enabled" : "Bootstrap disabled"}
        text="Disable only when the project should write into an already-managed repository."
        ariaLabel="Toggle repository bootstrap"
        onToggle={() => setProjectRepoBootstrapEnabled((value: boolean) => !value)}
      />
      <FormToggleRow
        on={projectRepoBootstrapAutoOnSessionStart}
        title={projectRepoBootstrapAutoOnSessionStart ? "Bootstrap on session start" : "Bootstrap on first write"}
        text="Use session-start bootstrap if you want the project checkout prepared before the first coding step."
        ariaLabel="Toggle auto bootstrap on session start"
        onToggle={() => setProjectRepoBootstrapAutoOnSessionStart((value: boolean) => !value)}
      />
      <div className="admin-form-help">
        Coding tools bootstrap a git repository before writing. Leaving this
        empty keeps the implicit local fallback; use this section to enforce a
        stored GitHub or Bitbucket strategy.
      </div>
      <div className="admin-panel__form-actions">
        <button
          type="submit"
          className="admin-panel__action-btn admin-panel__action-btn--primary"
          disabled={projectQualityLoading}
        >
          {projectQualityLoading ? "Saving…" : "Save Repository Bootstrap"}
        </button>
        <button
          type="button"
          className="admin-panel__action-btn"
          disabled={projectQualityLoading}
          onClick={() => void onUseImplicitLocalFallback()}
        >
          Use Implicit Local Fallback
        </button>
      </div>
    </form>
  );
}
