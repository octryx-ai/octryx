import { useCallback, useEffect, useId, useLayoutEffect, useRef, useState } from "react";
import { citationMarkerTarget, collectAnswerSources, describeSource, previewStatement } from "./answerSourceLinks";
import type { SourceOverview } from "./answerSourceLinks";
import "./answer-sources.css";

const EMPTY: SourceOverview = { sources: [], excluded: 0, truncated: false };

// The one entry from an answer to its evidence: a
// visible button with the number of cited sources that opens a right-side
// drawer with a compact, openable source list.
export function AnswerSourcesButton({ contentKey, quietWhenNone = false }: {
  contentKey: string;
  /** An intermediate tool step shows the chip only when it cites sources. */
  quietWhenNone?: boolean;
}) {
  const id = useId();
  // The chip, or (quiet with nothing cited) a hidden anchor that still finds the message to count its links.
  const button = useRef<HTMLElement | null>(null);
  const anchor = useCallback((node: HTMLElement | null) => { button.current = node; }, []);
  const dialog = useRef<HTMLDialogElement>(null);
  const [overview, setOverview] = useState<SourceOverview>(EMPTY);
  const [open, setOpen] = useState(false);
  // A source marker ([n]) in the answer opens this panel on its source instead of leaving the chat.
  const [focusUrl, setFocusUrl] = useState<string | null>(null);

  const collect = useCallback(() => {
    setOverview(collectAnswerSources(button.current?.closest("article.message-row") ?? null, window.location.origin));
  }, []);
  // Markdown is lazy-loaded under Suspense. Observe only the answer body so a
  // later render updates the count without reacting to this drawer's own links.
  useLayoutEffect(() => {
    collect();
    const body = button.current?.closest("article.message-row")?.querySelector(".message-bubble");
    if (!body) return;
    const observer = new MutationObserver(collect);
    observer.observe(body, { childList: true, subtree: true, characterData: true, attributes: true, attributeFilter: ["href"] });
    return () => observer.disconnect();
  }, [collect, contentKey]);

  useEffect(() => {
    const body = button.current?.closest("article.message-row")?.querySelector(".message-bubble");
    if (!body || typeof body.addEventListener !== "function") return;
    const onClick = (event: Event) => {
      const link = (event.target as Element | null)?.closest?.(".message-markdown a[href]");
      const url = link ? citationMarkerTarget(link, window.location.origin) : null;
      if (!url) return;
      event.preventDefault();
      setFocusUrl(url);
      openDrawerRef.current();
    };
    body.addEventListener("click", onClick);
    return () => body.removeEventListener("click", onClick);
  }, [contentKey]);
  useEffect(() => {
    if (!open || !focusUrl) return;
    const item = dialog.current?.querySelector<HTMLElement>(".answer-sources__item--focused");
    item?.scrollIntoView?.({ block: "nearest" });
  }, [open, focusUrl, overview]);

  const count = overview.sources.length;
  const openDrawer = () => { collect(); setOpen(true); if (!dialog.current?.open) dialog.current?.showModal(); };
  const openDrawerRef = useRef(openDrawer);
  openDrawerRef.current = openDrawer;
  const close = () => dialog.current?.close();

  if (quietWhenNone && !count) return <span ref={anchor} hidden data-testid="answer-sources-quiet" />;

  return <>
    <button ref={anchor} type="button"
      className={`answer-sources__button${count ? " answer-sources__button--has-sources" : ""}`}
      onClick={() => { setFocusUrl(null); openDrawer(); }} aria-haspopup="dialog">
      {count ? `Sources · ${count}` : "Sources · none cited"}
    </button>
    <dialog ref={dialog} className="answer-sources__dialog" aria-labelledby={`${id}-title`}
      onClose={() => setOpen(false)}
      onClick={(event) => { if (event.target === dialog.current) close(); }}>
      <div className="answer-sources__heading">
        <div>
          <span className="answer-sources__eyebrow">Answer evidence</span>
          <h2 id={`${id}-title`}>Sources &amp; evidence</h2>
        </div>
        <button type="button" className="answer-sources__close" onClick={close} aria-label="Close sources">
          <svg viewBox="0 0 20 20" aria-hidden="true"><path d="M5 5l10 10M15 5L5 15" /></svg>
        </button>
      </div>
      <p className="answer-sources__muted">
        Sources cited in this answer. A citation shows where a statement comes from; it does not verify the claim.
        Opening a source uses your own permissions.
      </p>
      <section className="answer-sources__section" aria-label="Cited sources">
        <h3>{count ? `${count} cited ${count === 1 ? "source" : "sources"}` : "Cited sources"}</h3>
        {count ? (
          <ol className="answer-sources__list">
            {overview.sources.map((source) => {
              const described = describeSource(source.url, window.location.origin);
              const preview = source.statement ? previewStatement(source.statement) : "";
              const focused = source.url === focusUrl;
              return <li key={source.url} className={`answer-sources__item${focused ? " answer-sources__item--focused" : ""}`}
                aria-current={focused ? "true" : undefined}>
                <a href={source.url} target="_blank" rel="noopener noreferrer">{source.label}</a>
                <span className="answer-sources__location">{described.location}</span>
                {preview ? (
                  preview.length < source.statement.length ? (
                    <details className="answer-sources__statement">
                      <summary>{preview}</summary>
                      <p>{source.statement}</p>
                    </details>
                  ) : <p className="answer-sources__statement">{preview}</p>
                ) : null}
              </li>;
            })}
          </ol>
        ) : <p className="answer-sources__muted">No openable source links were cited in this answer.</p>}
        {overview.excluded > 0 ? <p className="answer-sources__muted">{overview.excluded} unsafe or unsupported links are not listed.</p> : null}
        {overview.truncated ? <p className="answer-sources__muted">Only the first 100 links of the answer are listed.</p> : null}
      </section>
    </dialog>
  </>;
}
