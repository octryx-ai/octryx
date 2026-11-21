import { safeSourceUrl } from "../../../chat/evidence/answerSourceLinks";
import { originalContentUrl } from "../workspaceKnowledge/workspaceKnowledgeRequest";
import type { GraphEvidence } from "./entityGraphTypes";

export function EntityGraphCitation({ evidence, workspaceId }: { evidence: GraphEvidence; workspaceId: string }) {
  const website = evidence.source_url ? safeSourceUrl(evidence.source_url, window.location.origin) : null;
  const capturedSource = workspaceId && evidence.source_id && evidence.revision_id
    ? originalContentUrl(workspaceId, evidence.source_id, evidence.revision_id) : null;
  const citation = evidence.citation || evidence.source_title || "Source evidence";
  return <div className="admin-panel__note">
    <span title={evidence.source_title || "Source evidence"}>{citation}</span>
    {evidence.section && !citation.includes(evidence.section) ? <span> · § {evidence.section}</span> : null}
    {evidence.page && !citation.includes(`p. ${evidence.page}`) ? <span> · p. {evidence.page}</span> : null}
    {evidence.line ? <span> · line {evidence.line}</span> : null}
    {capturedSource ? <>{" · "}<a href={capturedSource} target="_blank" rel="noopener noreferrer">Open captured source</a></>
      : <span> · Captured source link unavailable</span>}
    {website ? <>{" · "}<a href={website} target="_blank" rel="noopener noreferrer">Original website</a></> : null}
  </div>;
}
