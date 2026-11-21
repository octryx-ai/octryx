import { useEffect, useState } from "react";

import {
  answerMarkers, answerStateText, requestKnowledgeAnswer, UNAVAILABLE_ANSWER, type KnowledgeAnswer as Answer,
} from "./answerApi";
import { KnowledgeSearchProgress } from "./KnowledgeSearchProgress";

type Loaded = { request: string; answer: Answer };

// The short cited answer above the hits. Asked once the hits are there, with their evidence keys; each
// sentence ends with numbered markers [n] that are the hit numbers on the page, and a marker opens that hit's
// preview. A marker is a button named after its source ("Source 3: Release notes"), so keyboard and screen readers
// reach it. Without an answer the page says why in one sentence and the hits stay the result.
export function KnowledgeAnswer({ workspaceId, query, evidenceKeys, numberOf, titleOf, onOpen, onAskInChat, loadAnswer = requestKnowledgeAnswer }: {
  workspaceId: string;
  query: string;
  evidenceKeys: string[];
  numberOf: ReadonlyMap<string, number>;
  titleOf?: ReadonlyMap<string, string>;
  onOpen: (evidenceKey: string) => void;
  onAskInChat: () => void;
  loadAnswer?: (workspaceId: string, query: string, evidenceKeys: string[]) => Promise<Answer>;
}) {
  const requestKey = JSON.stringify([workspaceId, query, evidenceKeys]);
  const [loaded, setLoaded] = useState<Loaded | null>(null);
  useEffect(() => {
    let current = true;
    const [id, text, keys] = JSON.parse(requestKey) as [string, string, string[]];
    if (!text.trim() || !keys.length) return undefined;
    Promise.resolve()
      .then(() => loadAnswer(id, text, keys))
      .then((answer) => { if (current) setLoaded({ request: requestKey, answer }); })
      .catch(() => { if (current) setLoaded({ request: requestKey, answer: UNAVAILABLE_ANSWER }); });
    return () => { current = false; };
  }, [requestKey, loadAnswer]);
  if (!query.trim() || !evidenceKeys.length) return null;
  const answer = loaded?.request === requestKey ? loaded.answer : null;
  return (
    <section className="knowledge-search__answer" aria-label="Short answer" data-testid="search-answer">
      {answer === null ? <KnowledgeSearchProgress stage="answer" /> : answer.state === "ok" ? (
        <p className="knowledge-search__answer-text">
          {answer.sentences.map((sentence, index) => (
            <span key={index}>
              {index ? " " : ""}{sentence.text}
              {answerMarkers(sentence.cites, numberOf).map((marker) => (
                <button key={marker.key} type="button" className="knowledge-search__cite" data-testid="answer-cite"
                  onClick={() => onOpen(marker.key)}
                  aria-label={marker.number === null
                    ? `Source: ${titleOf?.get(marker.key) ?? "cited passage"} (hidden by the filters)`
                    : `Source ${marker.number}: ${titleOf?.get(marker.key) ?? "cited passage"}`}>
                  [{marker.number ?? "·"}]
                </button>
              ))}
            </span>
          ))}
        </p>
      ) : (
        <p className="knowledge-search__hint" data-testid="answer-state">{answerStateText(answer.state)}</p>
      )}
      <div className="knowledge-search__answer-foot">
        <button type="button" className="admin-panel__action-btn" onClick={onAskInChat} data-testid="ask-in-chat">
          Ask in chat
        </button>
      </div>
    </section>
  );
}
