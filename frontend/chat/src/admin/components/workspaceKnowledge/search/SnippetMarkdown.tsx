import type { ReactNode } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

import { markTerms } from "./snippet";

// A passage as its source wrote it (no raw "## Description"): Markdown rendered, headings shown as
// bold lines so a snippet never outranks the hit title, links opening in a new tab, raw HTML never rendered.
// With `terms` the question's words are marked in the rendered text, never inside code or links.
const HEADING = ({ children }: { children?: ReactNode }) => <p className="knowledge-search__snippet-heading">{children}</p>;

type HastNode = { type: string; tagName?: string; value?: string; properties?: Record<string, unknown>; children?: HastNode[] };

const SKIP = new Set(["code", "pre", "a"]);

function markIn(node: HastNode, terms: string[]): void {
  if (!node.children || (node.tagName && SKIP.has(node.tagName))) return;
  node.children = node.children.flatMap((child): HastNode[] => {
    if (child.type !== "text" || !child.value) {
      markIn(child, terms);
      return [child];
    }
    return markTerms(child.value, terms).map((part) => (part.marked
      ? { type: "element", tagName: "mark", properties: { className: ["knowledge-search__term"] }, children: [{ type: "text", value: part.text }] }
      : { type: "text", value: part.text }));
  });
}

const markTermsPlugin = (terms: string[]) => () => (tree: HastNode) => { markIn(tree, terms); };

export function SnippetMarkdown({ text, className, terms }: { text: string; className?: string; terms?: string[] }) {
  return (
    <div className={`knowledge-search__snippet${className ? ` ${className}` : ""}`}>
      <ReactMarkdown remarkPlugins={[remarkGfm]} rehypePlugins={terms?.length ? [markTermsPlugin(terms)] : []} skipHtml
        components={{
          h1: HEADING, h2: HEADING, h3: HEADING, h4: HEADING, h5: HEADING, h6: HEADING,
          a: ({ href, children }) => <a href={href} target="_blank" rel="noopener noreferrer">{children}</a>,
          img: () => null,
        }}>
        {text.trim()}
      </ReactMarkdown>
    </div>
  );
}
