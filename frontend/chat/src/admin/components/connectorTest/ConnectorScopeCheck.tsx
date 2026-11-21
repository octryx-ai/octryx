import { configuredLines, visibleText } from "./scopeCheckModel";
import type { ScopeCheck } from "./scopeCheckModel";
import "./connectorScopeCheck.css";

// The scope part of a connection test (delivery 5): each configured key, visible or not, then what the
// account sees. A key the account cannot see is a warning, so a swapped account shows up right in the test.
export function ConnectorScopeCheck({ check }: { check: ScopeCheck }) {
  const lines = configuredLines(check);
  return (
    <div className="connector-scope-check" data-testid="connector-scope-check">
      {lines.length ? (
        <ul className="connector-card__test-details">
          {lines.map((line) => (
            <li key={line.key} data-visible={line.visible ? "yes" : "no"}
              className={line.visible ? undefined : "security-field-hint security-field-hint--attention"}>
              <strong>{line.visible ? "✓" : "⚠"}</strong> {line.text}
            </li>
          ))}
        </ul>
      ) : check.configured === null ? (
        <div className="connector-card__test-details">No {check.label.toLowerCase()} restriction is configured.</div>
      ) : null}
      <div className="connector-card__test-details">{visibleText(check)}</div>
    </div>
  );
}
