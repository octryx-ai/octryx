import { useEffect, useRef } from "react";

import { SearchIcon } from "./ChatShellIcons";

/** Always visible; `/` focuses it from anywhere outside a text field, Esc clears it. */
export function ThreadSearchBox({ value, onChange }: { value: string; onChange: (value: string) => void }) {
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null;
      const typing = target && (/INPUT|TEXTAREA|SELECT/.test(target.tagName) || target.isContentEditable);
      if (event.key === "/" && !typing && !event.metaKey && !event.ctrlKey && !event.altKey) {
        event.preventDefault();
        inputRef.current?.focus();
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, []);

  return (
    <div className="thread-search" role="search">
      <SearchIcon />
      <input
        ref={inputRef}
        type="search"
        value={value}
        placeholder="Search all chats"
        aria-label="Search all chats"
        onChange={(event) => onChange(event.target.value)}
        onKeyDown={(event) => {
          if (event.key === "Escape" && value) {
            event.stopPropagation();
            onChange("");
          }
        }}
      />
      {value ? null : (
        <span className="thread-search__kbd" aria-hidden="true">
          /
        </span>
      )}
    </div>
  );
}
