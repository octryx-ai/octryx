import { highlightCedar } from "./cedarHighlight";

export function CedarCode({ text, testId }: { text: string; testId?: string }) {
  return (
    <pre className="policies__code" data-testid={testId}>
      {highlightCedar(text).map((token, index) => (
        token.kind === "plain" ? token.text : <span key={index} className={`policies__code-${token.kind}`}>{token.text}</span>
      ))}
    </pre>
  );
}
