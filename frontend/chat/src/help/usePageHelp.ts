import { useEffect, useState } from "react";

import { AREA_TAB_EVENT } from "../chat/areaNavigation";
import { helpPageFromSearch } from "./helpDocs";

const OPEN_EVENT = "octryx:open-page-help";

/** Opens the help panel from anywhere in the app (for example a page's own Help button). */
export function openPageHelp() {
  if (typeof window !== "undefined") window.dispatchEvent(new Event(OPEN_EVENT));
}

/**
 * The help panel's open state. Help opens only when asked for (the ? in the rail or a page's Help button), never by
 * itself: opened on every first visit it covered a third of the page.
 */
export function usePageHelp() {
  const [open, setOpen] = useState(false);

  useEffect(() => {
    const show = () => setOpen(true);
    window.addEventListener(OPEN_EVENT, show);
    return () => window.removeEventListener(OPEN_EVENT, show);
  }, []);

  return [open, setOpen] as const;
}

const currentPage = () => (typeof window === "undefined" ? null : helpPageFromSearch(window.location.search));

/**
 * The page the address shows now. An area switches its pages in the address without a render of the shell, so this
 * follows every switch; otherwise the help of the page opened first would stay in the panel.
 */
export function useHelpPage(area: string): string | null {
  const [page, setPage] = useState(currentPage);

  useEffect(() => {
    const follow = () => setPage(currentPage());
    follow();
    window.addEventListener(AREA_TAB_EVENT, follow);
    window.addEventListener("popstate", follow);
    return () => {
      window.removeEventListener(AREA_TAB_EVENT, follow);
      window.removeEventListener("popstate", follow);
    };
  }, [area]);

  return page;
}
