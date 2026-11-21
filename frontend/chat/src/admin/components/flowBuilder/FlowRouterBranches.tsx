// Branch overview of an If / else step: where each branch continues and what happens to uncovered branches.
import type { BranchConnections, BranchCoverage } from "./flowBranchConnections";

// What happens when the step picks a branch without its own connection.
function BranchCoverageNote({ coverage }: { coverage: BranchCoverage }) {
  if (coverage.state === "no_connections") {
    return <div className="flow-conditional__note">Nothing is connected after this step yet, so the workflow ends here whichever branch is picked.</div>;
  }
  if (coverage.state === "complete") return null;
  if (coverage.state === "blocked") {
    return (
      <div className="flow-conditional__note flow-conditional__note--attention" role="status">
        This step cannot run until it is fixed ({coverage.reason}). The workflow stops here with an error, whichever branch would
        apply, and nothing after it runs.
      </div>
    );
  }
  const names = coverage.branches.map((name) => `“${name}”`).join(", ");
  if (coverage.state === "runtime") {
    return (
      <div className="flow-conditional__note flow-conditional__note--attention" role="status">
        Branch {names} has no connection of its own. A custom connection condition may still pick it when the workflow runs; if
        none does, the run stops at this step with an error and nothing after it runs. Connect the branch, or add one
        connection without a branch for all other cases.
      </div>
    );
  }
  return (
    <div className="flow-conditional__note flow-conditional__note--attention" role="status">
      Branch {names} has no connection. If the workflow picks it, the run stops at this step with an error and nothing after it
      runs. Connect the branch, or add one connection without a branch for all other cases.
    </div>
  );
}

export function FlowRouterBranches({ connections }: { connections: BranchConnections }) {
  return (
    <>
      <div className="flow-inspector__section-title">Branches and connections</div>
      <ul className="flow-conditional__branches" data-testid="router-branches">
        {connections.branches.map((branch) => (
          <li key={branch.name}>
            <strong>{branch.label}</strong> · branch <code>{branch.name}</code>:{" "}
            {!branch.reachable
              ? "never picked, because an earlier rule has no condition and always matches"
              : branch.targets.length
                ? `continues to ${branch.targets.join(", ")}`
                : "no connection of its own"}
          </li>
        ))}
        {connections.fallbackTargets.length ? (
          <li>
            <strong>Any branch without its own connection</strong> continues to {connections.fallbackTargets.join(", ")}
          </li>
        ) : null}
        {connections.customTargets.length ? (
          <li>
            <strong>Custom connection condition</strong> (kept as saved, decided when the workflow runs): {connections.customTargets.join(", ")}
          </li>
        ) : null}
        {connections.invalidCustomTargets.length ? (
          <li className="flow-conditional__note--attention">
            <strong>Connection condition that cannot be checked</strong> (kept as saved): {connections.invalidCustomTargets.join(", ")}
          </li>
        ) : null}
        {connections.neverTargets.map((target) => (
          <li key={`never:${target}`} className="flow-conditional__note--attention">
            The connection to {target} has a condition that never matches, so it never runs.
          </li>
        ))}
        {connections.orphanTargets.map((orphan) => (
          <li key={`${orphan.names.join("|")}:${orphan.target}`} className="flow-conditional__note--attention">
            The connection to {orphan.target} waits for branch{" "}
            {orphan.names.map((name, index) => (
              <span key={name}>
                {index ? " or " : ""}
                <code>{name}</code>
              </span>
            ))}
            , which no rule picks, so it never runs.
          </li>
        ))}
      </ul>
      <BranchCoverageNote coverage={connections.coverage} />
    </>
  );
}
