// Follows new steps only while the person is at the bottom of the page; otherwise it offers "New steps".

import { useEffect, useRef, useState, type MutableRefObject } from "react";

export function useFollowBottom(
  items: number,
  end: MutableRefObject<HTMLDivElement | null>,
  seen: MutableRefObject<number>,
) {
  // Follow new steps only when the person is at the bottom; reading further up, the page holds still and offers
  // "↓ New steps" (a tap that would land on a moving target is worse than no auto-scroll).
  const [newBelow, setNewBelow] = useState(false);
  const atBottom = useRef(true);
  useEffect(() => {
    const measure = () => {
      const root = document.documentElement;
      atBottom.current = window.innerHeight + window.scrollY >= root.scrollHeight - 120;
      if (atBottom.current) setNewBelow(false);
    };
    measure();
    window.addEventListener("scroll", measure, { passive: true });
    return () => window.removeEventListener("scroll", measure);
  }, []);
  useEffect(() => {
    if (items > seen.current) {
      if (atBottom.current || seen.current === 0) end.current?.scrollIntoView?.();
      else setNewBelow(true);
    }
    seen.current = items;
  }, [items, end, seen]);
  return [newBelow, setNewBelow] as const;
}
