import type { TestReport } from "./policyEngineVersions";
import { usePolicyLabel } from "./policyNames";

// The saved test cases' result for one policy text: a failing case blocks publishing.
export function PolicyTestReport({ report }: { report: TestReport }) {
  const label = usePolicyLabel();
  if (!report.total) return <p className="admin-panel__hint" data-testid="policy-tests-none">No saved test cases yet (Test bench tab).</p>;
  return (
    <div className={report.ok ? "admin-panel__success" : "workspace-classification__message"} role={report.ok ? "status" : "alert"} data-testid="policy-tests-report">
      <p>{report.ok ? `All ${report.total} saved test cases pass.` : `${report.failed} of ${report.total} saved test cases fail: publishing is blocked.`}</p>
      {report.failed ? (
        <ul>
          {report.results.filter((item) => !item.passed).map((item) => (
            <li key={item.id} data-testid="policy-tests-failure">
              {item.name}: expected {item.expected}, got {item.actual}{item.determining.length ? ` (by ${item.determining.map(label).join(", ")})` : ""}
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}
