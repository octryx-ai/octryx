import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

import { splitSkillMd } from "./skillCatalogModel";

// A rendered SKILL.md (or reference file) in theme tokens: the frontmatter as a key/value grid, the body as markdown.
// Raw HTML in the markdown is never rendered (react-markdown default), so an imported file cannot inject markup.
export function SkillMarkdown({ text, maxHeight, testId }: { text: string; maxHeight?: string; testId?: string }) {
  const { frontmatter, body } = splitSkillMd(text);
  const pairs = frontmatter
    .split(/\r?\n/)
    .map((line) => /^([A-Za-z0-9_-]+):\s?(.*)$/.exec(line))
    .filter((match): match is RegExpExecArray => match !== null);
  return (
    <div className="skills__preview" style={maxHeight ? { maxHeight } : undefined} data-testid={testId}>
      {pairs.length ? (
        <dl className="skills__fm">
          {pairs.map((match) => (
            <div key={match[1]} style={{ display: "contents" }}>
              <dt>{match[1]}</dt>
              <dd>{match[2] || "…"}</dd>
            </div>
          ))}
        </dl>
      ) : null}
      <ReactMarkdown remarkPlugins={[remarkGfm]}>{body}</ReactMarkdown>
    </div>
  );
}
