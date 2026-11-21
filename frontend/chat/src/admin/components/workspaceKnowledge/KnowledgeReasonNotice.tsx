import type { ReasonNotice } from "./runReasonNotice";

// An explicit policy refusal in a run report: title, fixed code and what it means. Never a URL or host.
export function KnowledgeReasonNotice({ notice }: { notice: ReasonNotice }) {
  return (
    <div className="security-refusal security-refusal--error" role="alert">
      <div className="security-refusal__head">
        <strong>{notice.title}</strong>
        <code className="security-refusal__code">{notice.code}</code>
      </div>
      <p className="security-refusal__text">{notice.text}</p>
    </div>
  );
}
