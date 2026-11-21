# PR review bot fixtures

Provider payloads in the shapes GitHub, GitLab, Bitbucket Cloud and Bitbucket Server/Data Center document and send
(trimmed to the fields the bot reads, plus neighbours that must be ignored). No real repository, user or token.

- `github_pull_request_synchronize.json` — `X-GitHub-Event: pull_request`, `action: synchronize`
- `bitbucket_cloud_pullrequest_updated.json` — `X-Event-Key: pullrequest:updated` (short 12-char source hash)
- `bitbucket_server_pr_from_ref_updated.json` — `eventKey: pr:from_ref_updated`
- `github_pulls_page.json`, `bitbucket_cloud_pullrequests_page.json`, `bitbucket_server_pull_requests_page.json` —
  the open pull request lists the hourly sync reads
- `gitlab_merge_request_hook.json` — `X-Gitlab-Event: Merge Request Hook`, `action: update` with `oldrev` (a push)
- `gitlab_note_hook.json` — `X-Gitlab-Event: Note Hook`, a reply in a diff discussion
- `gitlab_merge_requests_page.json` — the open merge request list (one ready, one draft, one from a fork)
- `gitlab_discussions.json` — a merge request's discussions (an overview note, a system note, a diff thread)
