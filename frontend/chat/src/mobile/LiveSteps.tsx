// The step rows of a live session: tool lines, tool groups and plain steps.

import { groupSummary, shortStep, type ProgressBlock, type ProgressStep, type ToolStep } from "./mobileLiveProgress";

export function ToolLine({ tool, open, onToggle }: { tool: ToolStep; open: boolean; onToggle: () => void }) {
  const failed = tool.done && !tool.ok;
  return (
    <button
      type="button"
      className={`m-step-row${failed ? " m-step-failed" : ""}`}
      aria-expanded={open}
      onClick={onToggle}
    >
      <span className="m-step-mark" aria-hidden="true">
        {!tool.done ? "…" : tool.ok ? "✓" : "✗"}
      </span>
      <span className="m-step-body">
        <b>{tool.tool}</b>
        {open ? (
          <>
            {tool.input && <span className="m-step-input m-step-full"> {tool.input}</span>}
            {tool.line && <span className="m-step-line">{tool.line}</span>}
          </>
        ) : (
          <span className="m-step-input"> {shortStep(tool)}</span>
        )}
        {!open && failed && tool.line && <span className="m-step-line">{tool.line}</span>}
      </span>
    </button>
  );
}

export function ToolGroup({
  group,
  open,
  openSteps,
  onToggle,
  onToggleStep,
}: {
  group: Extract<ProgressBlock, { kind: "tools" }>;
  open: boolean;
  openSteps: Set<string>;
  onToggle: () => void;
  onToggleStep: (key: string) => void;
}) {
  // Collapsed, the running step and failed ones stay visible: they are what needs attention.
  const shown = open ? group.tools : group.tools.filter((tool) => !tool.done || !tool.ok);
  return (
    <div className={`m-step-group${group.failed ? " m-step-failed" : ""}`}>
      <button type="button" className="m-step-summary" aria-expanded={open} onClick={onToggle}>
        <span className="m-step-mark" aria-hidden="true">
          {group.failed ? "✗" : group.running ? "…" : "✓"}
        </span>
        <span className="m-step-body">{groupSummary(group)}</span>
        <span className="m-step-chevron" aria-hidden="true">
          {open ? "▾" : "▸"}
        </span>
      </button>
      {shown.map((tool) => (
        <ToolLine
          key={tool.key}
          tool={tool}
          open={openSteps.has(tool.key)}
          onToggle={() => onToggleStep(tool.key)}
        />
      ))}
    </div>
  );
}

export function Step({ step }: { step: Exclude<ProgressStep, ToolStep> }) {
  if (step.kind === "text")
    return <div className="m-step m-step-text">{step.text}</div>;
  if (step.kind === "prompt")
    return (
      <div className="m-step m-step-prompt">
        {step.from ? `From ${step.from}: ` : "Asked: "}
        {step.text}
      </div>
    );
  return <div className="m-step m-step-compact">Context compacted</div>;
}
