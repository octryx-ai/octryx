import { useEffect, useRef, useState } from "react";
import { loadEpicProgress } from "./mobileApi";
import { epicsShown, readEpicCard, type EpicCard } from "./mobileEpicCards";
import type { Case } from "./mobileTasksModel";

// One card for the Epics among the listed tasks; an Epic whose progress cannot be read is left out, never guessed.
export function EpicCards({ items, onOpen }: { items: Case[]; onOpen: (item: Case) => void }) {
  const epics = epicsShown(items);
  const ids = epics.map((item) => item.id).join(",");
  const shown = useRef(epics);
  shown.current = epics;
  const [cards, setCards] = useState<EpicCard[]>([]);

  useEffect(() => {
    let cancelled = false;
    const wanted = shown.current;
    if (!wanted.length) {
      setCards([]);
      return undefined;
    }
    void Promise.all(wanted.map((item) => loadEpicProgress(item.id).then((raw) => readEpicCard(item, raw)).catch(() => null)))
      .then((read) => { if (!cancelled) setCards(read.filter((card): card is EpicCard => card !== null)); });
    return () => {
      cancelled = true;
    };
  }, [ids]);

  if (!cards.length) return null;
  return (
    <section className="m-epic-card m-group" aria-label="Epics">
      {cards.map((card) => (
        <button key={card.item.id} type="button" className="m-epic-row" onClick={() => onOpen(card.item)}>
          <span className="m-epic-line">{card.line}</span>
          <span className="m-epic-bar" aria-hidden="true">
            {card.segments.map((s) => <i key={s.lane} className={`m-epic-${s.lane}`} style={{ width: `${s.share}%` }} />)}
          </span>
        </button>
      ))}
    </section>
  );
}
