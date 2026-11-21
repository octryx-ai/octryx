import { lazy, useMemo, Suspense, type ReactNode } from "react";
import ReactMarkdown from "react-markdown";
import type { Components } from "react-markdown";
import remarkGfm from "remark-gfm";
import { CodeBlock } from "./MarkdownCodeBlock";
import { InsidePreContext } from "./insidePreContext";

const MarkdownMathRenderer = lazy(async () => ({
  default: (await import("./MarkdownMathRenderer")).MarkdownMathRenderer,
}));

function contentHasMath(content: string) {
  return (
    /(^|[^\w])\$\$[\s\S]+?\$\$/.test(content) ||
    /(^|[^\w])\$[^$\n]+\$/.test(content)
  );
}

const markdownComponents: Components = {
  table: ({ children }: { children?: ReactNode }) => (
    <div className="message-markdown__table-wrap">
      <table>{children}</table>
    </div>
  ),
  // A link in the answer opens in a new tab like the Sources drawer, so the conversation stays;
  // an in-page anchor (#…) stays in place.
  a: ({ node, href, children, ...props }) =>
    href && !href.startsWith("#") ? (
      <a {...props} href={href} target="_blank" rel="noopener noreferrer">
        {children}
      </a>
    ) : (
      <a {...props} href={href}>
        {children}
      </a>
    ),
};

export function MarkdownRenderer({
  content,
  theme,
}: {
  content: string;
  theme: "dark" | "light";
}) {
  const needsMath = useMemo(() => contentHasMath(content), [content]);
  const components: Components = {
    ...markdownComponents,
    pre: ({ children, node, ...props }) => (
      <InsidePreContext.Provider value={true}>
        <pre {...props}>{children}</pre>
      </InsidePreContext.Provider>
    ),
    code: ({ className, children, node, ...props }) => (
      <CodeBlock
        inline={Boolean((props as { inline?: boolean }).inline)}
        className={className}
        theme={theme}
      >
        {children}
      </CodeBlock>
    ),
  };

  return (
    <div className="message-markdown">
      {needsMath ? (
        <Suspense
          fallback={
            <div className="message-bubble__empty">Rendering message...</div>
          }
        >
          <MarkdownMathRenderer content={content} components={components} />
        </Suspense>
      ) : (
        <ReactMarkdown remarkPlugins={[remarkGfm]} components={components}>
          {content}
        </ReactMarkdown>
      )}
    </div>
  );
}
