import type { Segment } from "./policyCatalogModel";

// A policy in plain language: the server's segments, the verb red and bold, values bold.
export function PolicySentence({ segments, className = "policies__sentence", testId }: { segments: Segment[]; className?: string; testId?: string }) {
  return (
    <span className={className} data-testid={testId}>
      {segments.map((segment, index) => (
        segment.emphasis === "verb" ? <span key={index} className="policies__verb"><b>{segment.text}</b></span>
          : segment.emphasis === "value" ? <b key={index}>{segment.text}</b> : segment.text
      ))}
    </span>
  );
}
