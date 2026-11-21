import { useState } from "react";

import { formatClock } from "../../admin/utils/dateTime";
import { MarkdownRenderer } from "../MarkdownRenderer";
import { RedactedText } from "../redaction/RedactedText";
import { hasRedaction } from "./transcriptModel";
import { type DisplayItem } from "./transcriptEntryItems";

// One block of a transcript line (Full session transcripts). Messages show their text; thinking, tool
// calls, tool results and bookkeeping lines are folded and render their content only when opened, because one
// tool result can be several megabytes.

// A larger body is cut in the view (the stored line stays whole); "Show all" renders the rest.
const SHOWN_CHARS = 60_000;

function BlockBody({ value }: { value: string }) {
  const [all, setAll] = useState(false);
  const cut = !all && value.length > SHOWN_CHARS;
  return (
    <>
      <pre className="transcript-block__pre"><RedactedText value={cut ? value.slice(0, SHOWN_CHARS) : value} /></pre>
      {cut ? (
        <button type="button" className="ds-link-button transcript-block__more" onClick={() => setAll(true)}>
          Show all ({Math.round(value.length / 1000)}k characters)
        </button>
      ) : null}
    </>
  );
}

function theme(): "dark" | "light" {
  if (typeof document === "undefined") return "dark";
  return document.documentElement.getAttribute("data-theme") === "light" ? "light" : "dark";
}

function Meta({ item }: { item: DisplayItem }) {
  return (
    <span className="transcript-block__meta">
      {item.timestamp ? `${formatClock(item.timestamp, "")} · ` : ""}line {item.line}
    </span>
  );
}

export function TranscriptBlock({ item }: { item: DisplayItem }) {
  const [open, setOpen] = useState(!item.collapsed);
  const tone = item.error ? " transcript-block--error" : "";

  if (item.kind === "omitted") {
    return (
      <div className="transcript-block transcript-block--note" data-kind={item.kind}>
        <span className="transcript-block__label">{item.label}</span>
        {item.summary ? <span className="transcript-block__summary">{item.summary}</span> : null}
        <Meta item={item} />
      </div>
    );
  }

  if (item.kind === "user" || item.kind === "assistant") {
    return (
      <div className={`transcript-block transcript-block--message transcript-block--${item.kind}`} data-kind={item.kind}>
        <div className="transcript-block__head">
          <span className="transcript-block__label">{item.label}</span>
          <Meta item={item} />
        </div>
        {item.markdown && !hasRedaction(item.body) ? (
          <div className="transcript-block__markdown"><MarkdownRenderer content={item.body} theme={theme()} /></div>
        ) : (
          <div className="transcript-block__text"><RedactedText value={item.body} /></div>
        )}
      </div>
    );
  }

  return (
    <details className={`transcript-block transcript-block--fold${tone}`} data-kind={item.kind} open={open}
      onToggle={(event) => setOpen((event.currentTarget as HTMLDetailsElement).open)}>
      <summary className="transcript-block__head">
        <span className="tool-inline__badge transcript-block__badge">{item.label}</span>
        {item.summary ? <span className="transcript-block__summary"><RedactedText value={item.summary} /></span> : null}
        {item.error ? <span className="tool-inline__status tool-inline__status--error">failed</span> : null}
        <Meta item={item} />
      </summary>
      {open ? (item.body ? <BlockBody value={item.body} /> : <p className="transcript-block__empty">No content.</p>) : null}
    </details>
  );
}
