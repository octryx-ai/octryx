# Source-control actions

`scm.py` runs a run's branch, push and pull request steps. The run's `repository` names the provider and the
repository: `github:<owner>/<repo>`, `gitlab:<group>/<project>` or `bitbucket:<project key>/<repo slug>`. Each step
dispatches that provider's governed tools on the Workspace's named connection.

## Rules

- **Branch.** The name comes from the ticket key (`<type>/<KEY>-<slug>`), or from the repository record's
  `branch_naming_rule` with `{type}`, `{key}` and `{slug}` (`source_control/branch_naming.py`). The remote branch is
  created and the run's working copy is checked out on it.
- **Push.** The working copy is committed as `<KEY>: <title>` and pushed.
- **Succession.** An existing remote branch is adopted only when an earlier run of the same Work item created it and
  pushed every commit it has (`branch_adoption.py`); otherwise the step reports `branch_conflict`. An earlier run's
  open pull request on the branch is reused; one on another branch refuses (`pr_adoption.py`).
- **Pull request reviewers.** The requesting user is a reviewer through their linked SCM account (`pr_reviewers.py`;
  on Bitbucket Cloud their Atlassian account, `bitbucket_cloud.py`), plus the repository record's owners.
  - An unresolved requester never blocks the step: the pull request opens without them, mentions them and records
    `reviewer_skipped: requester_unresolved`.
  - When the connection signs in as the requester, they are the author (`tools/scm_requester_rule.py`): no reviewer
    is set for them, the description mentions them, the run records `reviewer_skipped: requester_is_author` and
    notifies them. The watched merge is unchanged.
  - The pull request is recorded on the Work item and on the run, for every provider.
- **Empty repository.** A repository without a commit has no default branch, so the remote branch cannot be created
  first. When creation fails and the prepare tool reports `repository_empty`, the run goes on in the prepared folder
  on its unborn branch (`context.repository_empty`). The base is Git's empty tree, so the review covers the whole
  first commit, and the push creates the branch. When the provider refuses a pull request because the target branch
  does not exist yet, the step fails with a sentence that says what a person does (create the default branch, then
  retry the step); it never opens a pull request into the branch itself.
