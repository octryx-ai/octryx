import { useEffect, useRef, useState, type ReactNode } from "react";
import { Virtuoso, type VirtuosoHandle } from "react-virtuoso";
import { DownArrowIcon } from "./composerIcons";

type TimelineContext = { footer?: ReactNode };

// Content that follows the last message inside the feed (a thread's live device job), so it sits right under the
// conversation instead of above the composer with the feed's empty height in between.
function TimelineFooter({ context }: { context?: TimelineContext }) {
  return context?.footer ? <>{context.footer}</> : null;
}

// Room above the first message, so it never starts flush under the chat header.
function TimelineHeader() {
  return <div className="workspace__feed-start" aria-hidden="true" />;
}

const TIMELINE_COMPONENTS = { Header: TimelineHeader, Footer: TimelineFooter };

export function MessageTimeline<T>({
  items,
  followKey,
  onReachStart,
  renderItem,
  emptyState,
  footer,
}: {
  items: T[];
  followKey?: string | number;
  onReachStart?: () => void;
  renderItem: (item: T, index: number) => ReactNode;
  emptyState: ReactNode;
  footer?: ReactNode;
}) {
  const virtuosoRef = useRef<VirtuosoHandle | null>(null);
  const [isAtBottom, setIsAtBottom] = useState(true);
  const [isAtTop, setIsAtTop] = useState(false);
  // Deliberately NOT using initialTopMostItemIndex: react-virtuoso gates the
  // whole list behind a chain of requestAnimationFrame ticks for it, and
  // frames never fire while the document is hidden (background tab,
  // embedded/headless view), leaving the feed permanently invisible. The
  // effect below scrolls to the latest message instead.
  const initialScrollDoneRef = useRef(false);

  useEffect(() => {
    if (!items.length) {
      // Virtuoso is unmounted (empty state); the next mount positions again.
      initialScrollDoneRef.current = false;
      return;
    }
    if (initialScrollDoneRef.current && !isAtBottom) {
      return;
    }
    const frame = window.requestAnimationFrame(() => {
      virtuosoRef.current?.scrollToIndex({
        index: items.length - 1,
        align: "end",
        behavior: "auto",
      });
      initialScrollDoneRef.current = true;
    });
    return () => window.cancelAnimationFrame(frame);
  }, [followKey, isAtBottom, items.length]);

  if (!items.length) {
    return <div className="workspace__feed">{emptyState}{footer}</div>;
  }
  return (
    <div className="workspace__feed-shell">
      {!isAtTop ? (
        <button
          type="button"
          className="workspace__jump-start"
          title="Jump to start"
          aria-label="Jump to start"
          onClick={() =>
            virtuosoRef.current?.scrollToIndex({
              index: 0,
              align: "start",
              behavior: "auto",
            })
          }
        >
          <DownArrowIcon />
        </button>
      ) : null}
      <Virtuoso
        ref={virtuosoRef}
        className="workspace__feed workspace__feed--virtualized"
        data={items}
        context={{ footer }}
        components={TIMELINE_COMPONENTS}
        computeItemKey={(index) => {
          const item = items[index] as { id?: string | number } | undefined;
          return String(item?.id ?? index);
        }}
        atBottomThreshold={24}
        atBottomStateChange={setIsAtBottom}
        atTopStateChange={setIsAtTop}
        startReached={() => {
          // The list mounts scrolled to the top for an instant before the
          // initial jump to the latest message; loading older messages then
          // would be spurious.
          if (initialScrollDoneRef.current) {
            onReachStart?.();
          }
        }}
        followOutput={false}
        increaseViewportBy={{ top: 400, bottom: 800 }}
        // Apply ResizeObserver measurements synchronously instead of deferring
        // to an animation frame, for the same hidden-document reason as above.
        skipAnimationFrameInResizeObserver
        itemContent={(index, item) => (
          <div className="message-stack__item">{renderItem(item, index)}</div>
        )}
      />
      {!isAtBottom ? (
        <button
          type="button"
          className="workspace__jump-latest"
          title="Jump to latest"
          aria-label="Jump to latest"
          onClick={() =>
            virtuosoRef.current?.scrollToIndex({
              index: items.length - 1,
              align: "end",
              behavior: "auto",
            })
          }
        >
          <DownArrowIcon />
        </button>
      ) : null}
    </div>
  );
}
