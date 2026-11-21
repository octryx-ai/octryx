import { placeholderMeanings } from "./promptCatalogModel";

type Props = { placeholders: string[]; descriptions?: Record<string, string> };

// The placeholders a text may use, each with its short meaning from the key spec (backend); a name without a
// meaning is still listed, so the closed set is always complete.
export function PromptPlaceholderList({ placeholders, descriptions }: Props) {
  if (!placeholders.length) return <span className="ws-muted">No placeholders: the text is used as written.</span>;
  return (
    <ul className="pc-placeholders" data-testid="pc-placeholders">
      {placeholderMeanings(placeholders, descriptions).map(({ name, meaning }) => (
        <li key={name}>
          <code className="ws-mono pc-chip">{`{${name}}`}</code>
          {meaning ? <span className="pc-placeholders__meaning">{meaning}</span> : null}
        </li>
      ))}
    </ul>
  );
}
