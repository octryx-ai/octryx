import "./governedWrite.css";
import type { GovernedIssue } from "./governedRequest";

type Props = {
  issues: GovernedIssue[];
  tone?: "error" | "warning";
  label: string;
};

// Server refusals exactly as stated: each line shows the machine code and its message.
export function GovernedIssueList({ issues, tone = "error", label }: Props) {
  if (!issues.length) return null;
  return (
    <ul
      className={`governed-issues${tone === "warning" ? " governed-issues--warning" : ""}`}
      aria-label={label}
    >
      {issues.map((issue, index) => (
        <li key={`${issue.code}-${index}`} data-issue-code={issue.code}>
          <code>{issue.code}</code>
          {issue.message ? ` — ${issue.message}` : null}
        </li>
      ))}
    </ul>
  );
}
