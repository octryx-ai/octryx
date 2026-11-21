import { useEffect, useState } from "react";

import { answerProgressText, searchProgressText } from "./searchProgress";

// The running search: the outline of the coming results and a line with the elapsed seconds, so 10 s
// never look like nothing happens. The "answer" stage is the short answer written after the hits arrived.
export function KnowledgeSearchProgress({ stage = "search" }: { stage?: "search" | "answer" }) {
  const [seconds, setSeconds] = useState(0);
  useEffect(() => {
    if (typeof setInterval !== "function") return undefined;
    const started = Date.now();
    const timer = setInterval(() => setSeconds(Math.floor((Date.now() - started) / 1000)), 1000);
    return () => { if (typeof clearInterval === "function") clearInterval(timer); };
  }, []);
  return (
    <div className="knowledge-search__progress" data-testid={stage === "answer" ? "answer-progress" : "search-progress"}>
      <p role="status" className="knowledge-search__hint">
        {stage === "answer" ? answerProgressText(seconds) : searchProgressText(seconds)}
      </p>
      <div className="knowledge-search__progress-rows" aria-hidden="true">
        {(stage === "answer" ? [0] : [0, 1, 2]).map((row) => <div key={row} className="knowledge-search__progress-row" />)}
      </div>
    </div>
  );
}
