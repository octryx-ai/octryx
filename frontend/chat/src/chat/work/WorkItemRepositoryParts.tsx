import type { ReactNode } from "react";

import type { WorkChangeUnit, WorkPullRequest } from "./workPullRequestTypes";
import { Badge } from "./WorkAreaViews";
import { asArray, isHttpUrl, stringifyValue } from "./workItemDetailValues";
import { ExternalEvidenceLink } from "./WorkItemDetailParts";

// The detail's repository blocks: pull requests of the item and the repository impact of its change units.

export function PullRequestList({ pullRequests }: { pullRequests: WorkPullRequest[] }) {
  if (pullRequests.length === 0) return <p className="work-detail__empty">No Bitbucket PR linked yet.</p>;
  return (
    <ul className="work-detail__object-list work-detail__pr-list">
      {pullRequests.map((pullRequest) => (
        <li key={pullRequest.id}>
          <div className="work-detail__pr-header">
            <a href={pullRequest.pr_url} target="_blank" rel="noreferrer">
              {pullRequest.repository_slug} {pullRequest.pr_key || `#${pullRequest.pr_id}`}
            </a>
            <Badge value={pullRequest.status} />
            <Badge value={pullRequest.build_status || "build not captured"} />
          </div>
          <div>
            <BranchReference pullRequest={pullRequest} />
          </div>
          <div>{pullRequest.reviewers.length} reviewers, {pullRequest.approvals.length} approvals</div>
          {pullRequest.mismatches.length > 0 ? (
            <div className="work-pr__mismatches">
              {pullRequest.mismatches.map((mismatch) => (
                <span key={`${pullRequest.id}-${mismatch.type}`} className={`work-pr__mismatch is-${mismatch.severity}`}>
                  {mismatch.type.replaceAll("_", " ")}
                </span>
              ))}
            </div>
          ) : null}
        </li>
      ))}
    </ul>
  );
}

export function RepositoryImpactMap({
  changeUnits,
  pullRequests,
}: {
  changeUnits: WorkChangeUnit[];
  pullRequests: WorkPullRequest[];
}) {
  if (changeUnits.length === 0) {
    return (
      <p className="work-detail__empty">
        No approved repository execution units captured yet. Generated Work Plan scope appears below.
      </p>
    );
  }
  return (
    <div className="work-impact-map">
      {changeUnits.map((unit) => (
        <article key={unit.id} className="work-impact-map__unit">
          <header>
            <strong>
              <RepositoryReference unit={unit} pullRequests={pullRequests} />
            </strong>
            <Badge value={unit.status} />
          </header>
          <div className="work-impact-map__route">
            <ImpactStep label="Branch" value={<UnitBranchReference unit={unit} pullRequests={pullRequests} />} />
            <ImpactStep label="PR" value={<ExternalEvidenceLink href={unit.pr_link} label={unit.pr_link || "Not linked"} />} />
            <ImpactStep label="Tests" value={unit.validation_commands.join(", ") || "Not configured"} />
            <ImpactStep label="Reviewers" value={reviewerText(unit.reviewer_policy)} />
          </div>
          {unit.scope ? <p>{unit.scope}</p> : null}
          {unit.expected_paths.length > 0 ? (
            <div className="work-impact-map__chips">
              {unit.expected_paths.map((path) => (
                <span key={path}>{path}</span>
              ))}
            </div>
          ) : null}
          {unit.missing_profile_fields.length > 0 ? (
            <div className="work-impact-map__missing">
              Missing profile data: {unit.missing_profile_fields.join(", ")}
            </div>
          ) : null}
        </article>
      ))}
    </div>
  );
}

function BranchReference({ pullRequest }: { pullRequest: WorkPullRequest }) {
  const sourceUrl = branchBrowseUrl(pullRequest.repository_url, pullRequest.source_branch);
  const targetUrl = branchBrowseUrl(pullRequest.repository_url, pullRequest.target_branch);
  return (
    <span className="work-detail__link-row">
      <ExternalEvidenceLink href={sourceUrl} label={pullRequest.source_branch || "-"} />
      {pullRequest.target_branch ? <span>to</span> : null}
      <ExternalEvidenceLink href={targetUrl} label={pullRequest.target_branch || ""} />
    </span>
  );
}

function RepositoryReference({
  unit,
  pullRequests,
}: {
  unit: WorkChangeUnit;
  pullRequests: WorkPullRequest[];
}) {
  const pullRequest = matchingPullRequest(unit, pullRequests);
  return <ExternalEvidenceLink href={pullRequest?.repository_url} label={unit.repository_name} />;
}

function UnitBranchReference({
  unit,
  pullRequests,
}: {
  unit: WorkChangeUnit;
  pullRequests: WorkPullRequest[];
}) {
  const pullRequest = matchingPullRequest(unit, pullRequests);
  const href = branchBrowseUrl(pullRequest?.repository_url, unit.branch_name);
  return <ExternalEvidenceLink href={href} label={unit.branch_name || "Not planned"} />;
}


function ImpactStep({ label, value }: { label: string; value: ReactNode }) {
  return (
    <div>
      <dt>{label}</dt>
      <dd>{value}</dd>
    </div>
  );
}

function matchingPullRequest(unit: WorkChangeUnit, pullRequests: WorkPullRequest[]): WorkPullRequest | null {
  return (
    pullRequests.find((pullRequest) => pullRequest.change_unit_id === unit.id) ||
    pullRequests.find(
      (pullRequest) =>
        pullRequest.repository_slug === unit.repository_name ||
        pullRequest.repository_url?.includes(`/repos/${unit.repository_name}/`),
    ) ||
    null
  );
}

function branchBrowseUrl(repositoryUrl?: string | null, branchName?: string | null): string | null {
  const branch = String(branchName || "").trim();
  const rawUrl = String(repositoryUrl || "").trim();
  if (!branch || !isHttpUrl(rawUrl)) return null;
  const browseUrl = rawUrl.includes("/browse") ? rawUrl : `${rawUrl.replace(/\/$/, "")}/browse`;
  const separator = browseUrl.includes("?") ? "&" : "?";
  return `${browseUrl}${separator}at=${encodeURIComponent(`refs/heads/${branch}`)}`;
}



function reviewerText(policy: Record<string, unknown>): string {
  const required = asArray(policy.required_reviewers).map(stringifyValue).filter((value) => value !== "-");
  const defaults = asArray(policy.default_reviewers).map(stringifyValue).filter((value) => value !== "-");
  const owners = asArray(policy.owners).map(stringifyValue).filter((value) => value !== "-");
  return [...required, ...defaults, ...owners].join(", ") || "Not configured";
}
