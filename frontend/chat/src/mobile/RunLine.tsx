import { runLineRest, type RunLine } from "./engineSeatModel";

export function RunLineSubline({ line, more = [] }: { line: RunLine; more?: (string | null | undefined)[] }) {
  return (
    <span className="m-muted" data-testid="m-run-line">
      <span className="m-tag m-tag--lead" data-testid="engine-badge">
        {line.engine}
      </span>
      {runLineRest(line, ...more)}
    </span>
  );
}
