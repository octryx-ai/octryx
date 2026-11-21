import { Fragment, type ReactNode } from "react";

import { wikiBlocks, type WikiInline } from "./jiraWikiMarkup";

// A Jira description or comment rendered from its wiki markup (jiraWikiMarkup.ts): code blocks, headings, lists,
// quotes, bold, italics, underline and links. Everything is React text, never HTML; links only for http(s)/mailto.

function Inline({ parts }: { parts: WikiInline[] }) {
  return <>{parts.map((part, index) => <Fragment key={index}>{inlineNode(part)}</Fragment>)}</>;
}

function inlineNode(part: WikiInline): ReactNode {
  switch (part.kind) {
    case "text": return part.text;
    case "code": return <code>{part.text}</code>;
    case "link": return <a href={part.href} target="_blank" rel="noopener noreferrer">{part.text}</a>;
    case "strong": return <strong><Inline parts={part.children} /></strong>;
    case "em": return <em><Inline parts={part.children} /></em>;
    case "underline": return <u><Inline parts={part.children} /></u>;
    case "strike": return <s><Inline parts={part.children} /></s>;
  }
}

function Lines({ lines }: { lines: WikiInline[][] }) {
  return <>{lines.map((line, index) => <span key={index}>{index ? <br /> : null}<Inline parts={line} /></span>)}</>;
}

export function JiraWikiText({ text, empty, testId }: { text: string | null | undefined; empty: string; testId?: string }) {
  const blocks = wikiBlocks(text);
  if (!blocks.length) return <p data-testid={testId}>{empty}</p>;
  return (
    <div className="work-detail__stack work-detail__wiki" data-testid={testId}>
      {blocks.map((block, index) => {
        if (block.kind === "code") {
          return <pre key={index} className="work-detail__code" data-language={block.language || undefined}>
            <code>{block.text}</code>
          </pre>;
        }
        if (block.kind === "heading") {
          // Inside the detail's own section headings (h3), Jira headings start one level below.
          const Tag = (`h${Math.min(6, block.level + 3)}`) as "h4" | "h5" | "h6";
          return <Tag key={index}><Inline parts={block.content} /></Tag>;
        }
        if (block.kind === "list") {
          const items = block.items.map((item, itemIndex) => <li key={itemIndex}><Inline parts={item} /></li>);
          return block.ordered ? <ol key={index}>{items}</ol> : <ul key={index}>{items}</ul>;
        }
        if (block.kind === "quote") return <blockquote key={index}><Lines lines={block.lines} /></blockquote>;
        return <p key={index}><Lines lines={block.lines} /></p>;
      })}
    </div>
  );
}
