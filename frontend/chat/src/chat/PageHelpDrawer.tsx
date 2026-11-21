import { useEffect, useState, type MouseEvent } from "react";
import ReactMarkdown, { defaultUrlTransform } from "react-markdown";
import remarkGfm from "remark-gfm";

import { helpLinkTarget, resolveHelpDoc, type HelpLinkTarget } from "../help/helpDocs";
import { HELP_DOCS } from "../help/helpLibrary";
import { GUIDE_PAGES } from "../help/guideLibrary";
import { findGuidePage, guideContents, guideLink, type GuideRef } from "../help/helpGuides";
import type { WorkspaceArea } from "./workspaceAreas";
import { SETUP_GUIDE_HREF } from "./setup/setupGuideModel";
import { isAdminAreaKey, resolveAdminSidebarTab } from "../admin/config/adminPanelAreas";
import type { AdminTab } from "../admin/types/adminPanelTypes.governance";

type PageHelpDrawerProps = {
  area: WorkspaceArea;
  page: string | null;
  onClose: () => void;
  // Opens the page behind an in-app help link; the panel stays open so the next step can be read alongside.
  onNavigate?: (target: HelpLinkTarget) => void;
};

// The help panel: a side panel next to the page, not a modal, reading help/<area>/<page>.md. It opens
// only when asked for (the ? in the rail, a page's Help button), so it needs no switch against opening by itself.
export function PageHelpDrawer({ area, page, onClose, onNavigate }: PageHelpDrawerProps) {
  // The Setup guide's area (`help`) reads help/setup/*.md. A hidden page without its own file shows the help of the
  // entry it belongs to (Explore's Graph view reads Explore's help).
  const helpArea = area === "help" ? "setup" : area;
  const ownFile = Boolean(page) && HELP_DOCS.some((entry) => entry.area === helpArea && entry.page === page);
  const helpPage = page && !ownFile && isAdminAreaKey(helpArea) ? resolveAdminSidebarTab(helpArea, page as AdminTab) : page;
  const doc = resolveHelpDoc(HELP_DOCS, helpArea, helpPage);
  // A guide page opened from a `guide:` link replaces the page help until "Back"; a new page starts at its help.
  const [guideRef, setGuideRef] = useState<GuideRef | null>(null);
  useEffect(() => setGuideRef(null), [area, page]);
  const guide = guideRef ? findGuidePage(GUIDE_PAGES, guideRef) : null;

  useEffect(() => {
    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") onClose();
    }
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [onClose]);

  function openLink(event: MouseEvent<HTMLAnchorElement>, href: string) {
    const target = helpLinkTarget(href);
    // A link with more than area and page (a Work view, a Workspace) loads as a normal link.
    if (!target || !onNavigate || Object.keys(target.params).length) return;
    event.preventDefault();
    onNavigate(target);
  }

  const title = guide?.title || doc?.title || "Help";
  const body = guide?.body ?? doc?.body;
  const contents = guide ? guideContents(GUIDE_PAGES, guide.guide) : [];
  return (
    <aside className="page-help" aria-label={`${title} help`} data-testid="page-help">
      <div className="page-help__drawer">
        <header className="page-help__header">
          <h2>{title}</h2>
          <button type="button" className="page-help__close" onClick={onClose} aria-label="Close help">
            Close
          </button>
        </header>
        <div className="page-help__content">
          {guide ? (
            <button type="button" className="page-help__back" onClick={() => setGuideRef(null)}>
              ← Back to the page help
            </button>
          ) : null}
          {body ? (
            <ReactMarkdown
              remarkPlugins={[remarkGfm]}
              urlTransform={(url) => (guideLink(url) ? url : defaultUrlTransform(url))}
              components={{
                a: ({ href = "", children }) =>
                  guideLink(href) ? (
                    <a href={href} data-testid="page-help-guide-link"
                      onClick={(event) => { event.preventDefault(); setGuideRef(guideLink(href)); }}>{children}</a>
                  ) : helpLinkTarget(href) ? (
                    <a href={href} onClick={(event) => openLink(event, href)}>{children}</a>
                  ) : (
                    <a href={href} target="_blank" rel="noreferrer">{children}</a>
                  ),
              }}
            >
              {body}
            </ReactMarkdown>
          ) : (
            <p>There is no help for this page yet.</p>
          )}
          {contents.length > 1 ? (
            <nav className="page-help__guide-contents" aria-label="In this guide">
              <h3>In this guide</h3>
              {guide?.page === "index" ? null : (
                <a href={`guide:${guide?.guide}/index`} className="page-help__guide-overview"
                  onClick={(event) => { event.preventDefault(); if (guide) setGuideRef({ guide: guide.guide, page: "index" }); }}>
                  Overview
                </a>
              )}
              <ol>
                {contents.filter((item) => item.page !== "index").map((item) => (
                  <li key={item.page}>
                    {item.page === guide?.page ? <strong aria-current="page">{item.title}</strong> : (
                      <a href={`guide:${item.guide}/${item.page}`}
                        onClick={(event) => { event.preventDefault(); setGuideRef({ guide: item.guide, page: item.page }); }}>
                        {item.title}
                      </a>
                    )}
                  </li>
                ))}
              </ol>
            </nav>
          ) : null}
        </div>
        <nav className="page-help__guide" aria-label="Setup">
          <a href={SETUP_GUIDE_HREF} onClick={(event) => openLink(event, SETUP_GUIDE_HREF)}>Setup guide</a>
        </nav>
      </div>
    </aside>
  );
}
