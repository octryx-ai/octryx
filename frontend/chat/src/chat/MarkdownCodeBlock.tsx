// Code in a markdown answer: inline code, reference lists, compact technical output and highlighted blocks.

import { useContext, useEffect, useState, type ReactNode } from "react";
import { InsidePreContext } from "./insidePreContext";
import { loadCodeHighlighterRuntime, type CodeHighlighterRuntime } from "./codeHighlighterRuntime";
import {
  extractLanguage,
  extractReferenceTitle,
  isTechnicalToken,
  normalizeCodeLines,
  referenceKindLabel,
  shouldRenderCompactCode,
  shouldRenderReferenceList,
} from "./codeBlockHeuristics";

function ReferenceList({ value }: { value: string }) {
  const entries = normalizeCodeLines(value);
  return (
    <div className="message-reference-list">
      {entries.map((entry) => (
        <div key={entry} className="message-reference-item">
          <div className="message-reference-item__main">
            <div className="message-reference-item__header">
              <div className="message-reference-item__title">
                {extractReferenceTitle(entry)}
              </div>
              <span className="message-reference-item__kind" aria-hidden="true">
                {referenceKindLabel(entry)}
              </span>
            </div>
            <div className="message-reference-item__path">{entry}</div>
          </div>
        </div>
      ))}
    </div>
  );
}

export function CodeBlock({
  inline,
  className,
  children,
  theme,
}: {
  inline?: boolean;
  className?: string;
  children?: ReactNode;
  theme: "dark" | "light";
}) {
  const insidePre = useContext(InsidePreContext);
  inline = inline || !insidePre;
  const [copied, setCopied] = useState(false);
  const [runtime, setRuntime] = useState<CodeHighlighterRuntime | null>(null);
  const value = String(children ?? "").replace(/\n$/, "");
  useEffect(() => {
    if (inline) {
      return undefined;
    }
    let cancelled = false;
    void loadCodeHighlighterRuntime().then((nextRuntime) => {
      if (!cancelled) {
        setRuntime(nextRuntime);
      }
    });
    return () => {
      cancelled = true;
    };
  }, [inline]);
  if (inline) {
    return <code className={className}>{children}</code>;
  }
  const language = extractLanguage(className);
  const copyCode = async () => {
    try {
      await navigator.clipboard.writeText(value);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1500);
    } catch {
      setCopied(false);
    }
  };
  if (shouldRenderReferenceList(language, value)) {
    return <ReferenceList value={value} />;
  }
  if (shouldRenderCompactCode(language, value)) {
    const compactLines = normalizeCodeLines(value);
    const isSingleToken =
      compactLines.length === 1 && isTechnicalToken(compactLines[0] || "");
    return (
      <div
        className={`message-code-inline${isSingleToken ? " message-code-inline--token" : ""}`}
      >
        <code className="message-code-inline__value">
          {compactLines.join("\n")}
        </code>
      </div>
    );
  }
  const isPlainTextBlock = ["text", "txt", "plaintext"].includes(language);
  if (isPlainTextBlock) {
    return (
      <div className="message-code-block message-code-block--plain">
        <div className="message-code-block__toolbar message-code-block__toolbar--plain">
          <button
            type="button"
            className="message-code-block__copy"
            onClick={() => void copyCode()}
          >
            {copied ? "Copied" : "Copy"}
          </button>
        </div>
        <pre className="message-code-block__plain-body">{value}</pre>
      </div>
    );
  }
  return (
    <div className="message-code-block">
      <div className="message-code-block__toolbar">
        <span className="message-code-block__language">{language}</span>
        <button
          type="button"
          className="message-code-block__copy"
          onClick={() => void copyCode()}
        >
          {copied ? "Copied" : "Copy"}
        </button>
      </div>
      {runtime ? (
        <runtime.SyntaxHighlighter
          language={language}
          style={theme === "light" ? runtime.oneLight : runtime.oneDark}
          customStyle={{
            margin: 0,
            borderRadius: "0 0 var(--ds-radius-lg) var(--ds-radius-lg)",
            fontSize: "var(--ds-text-sm)",
          }}
          PreTag="div"
        >
          {value}
        </runtime.SyntaxHighlighter>
      ) : (
        <pre className="message-code-block__fallback">{value}</pre>
      )}
    </div>
  );
}
