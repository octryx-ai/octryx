import { TimeText } from "../../../utils/TimeText";
import { instanceSchedulerState } from "../connectorFreshness";
import type { EntryOverview } from "../../../../chat/knowledge/useKnowledgeEntryOverview";
import { exampleQuestions, startSources } from "./searchStartModel";

const TONE_DOT: Record<string, string> = { active: "ok", warning: "attention", danger: "attention", inactive: "muted" };

// Knowledge › Search before the first search: instead of an empty area, three example
// questions made from this workspace's sources (a click runs one) and the sources search reads, each with its state
// and last sync. Nothing here changes anything; it renders nothing while the sources are loading or there are none.
export function KnowledgeSearchStart({ overview, onAsk }: { overview: EntryOverview; onAsk: (question: string) => void }) {
  const connectors = overview.connectors?.connectors ?? [];
  const schedulingOn = instanceSchedulerState(overview.connectors) !== "off";
  const sources = startSources(connectors, schedulingOn);
  const questions = exampleQuestions(connectors, overview.listing?.sources ?? []);
  const more = connectors.length - sources.length;
  if (!questions.length && !sources.length) return null;
  return (
    <div className="knowledge-search__start" data-testid="search-start">
      {questions.length ? (
        <section className="knowledge-search__start-part" aria-labelledby="knowledge-search-try">
          <h2 id="knowledge-search-try" className="knowledge-search__start-head">Try asking</h2>
          <ul className="knowledge-search__examples">
            {questions.map((question) => (
              <li key={question}>
                <button type="button" className="knowledge-search__example" data-testid="search-example"
                  onClick={() => onAsk(question)}>{question}</button>
              </li>
            ))}
          </ul>
        </section>
      ) : null}
      {sources.length ? (
        <section className="knowledge-search__start-part" aria-labelledby="knowledge-search-sources">
          <h2 id="knowledge-search-sources" className="knowledge-search__start-head">Searches these sources</h2>
          <ul className="knowledge-search__sources" data-testid="search-start-sources">
            {sources.map((source) => (
              <li key={source.key} className="knowledge-search__source" title={source.reason ?? undefined}>
                <span className={`knowledge-search__dot knowledge-search__dot--${TONE_DOT[source.tone] ?? "muted"}`} aria-hidden="true" />
                <span className="knowledge-search__source-name" title={source.name}>{source.name}</span>
                <span className="knowledge-search__source-meta">
                  {source.origin} · {source.state}
                  {source.at !== null && source.state !== "Syncing" ? <> · <TimeText value={source.at} mode="recent" /></> : null}
                </span>
              </li>
            ))}
          </ul>
          {more > 0 ? <p className="knowledge-search__hint">and {more} more {more === 1 ? "source" : "sources"}</p> : null}
        </section>
      ) : null}
    </div>
  );
}
