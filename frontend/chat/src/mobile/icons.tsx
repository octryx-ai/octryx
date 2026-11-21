// The phone's icons: one set, 24 px grid, 1.75 px stroke, round caps, drawn in the text colour (design guide: icons
// consistent in size and stroke). Decorative by default; the button around an icon carries the name.

const PATHS = {
  home: "M4 10.5 12 4l8 6.5V19a1 1 0 0 1-1 1h-4.5v-5.5h-5V20H5a1 1 0 0 1-1-1z",
  chats: "M20 14.5a2 2 0 0 1-2 2H9l-4.5 3.5V6.5a2 2 0 0 1 2-2H18a2 2 0 0 1 2 2z",
  runs: "M12 3.5a8.5 8.5 0 1 0 0 17 8.5 8.5 0 0 0 0-17zM10 8.8v6.4l5.2-3.2z",
  work: "M9 4.5h6v3H9zM15 5.5h2.5a1 1 0 0 1 1 1V19a1 1 0 0 1-1 1h-11a1 1 0 0 1-1-1V6.5a1 1 0 0 1 1-1H9M9 13l2 2 4-4",
  more: "M5.5 12h.01M12 12h.01M18.5 12h.01",
  back: "m14.5 5.5-6.5 6.5 6.5 6.5",
  chevronDown: "m7 9.5 5 5 5-5",
  chevronRight: "m9.5 6 6 6-6 6",
  check: "m5 12.5 4.5 4.5L19 7.5",
  plus: "M12 5v14M5 12h14",
  close: "M6 6l12 12M18 6 6 18",
  refresh: "M19.5 12a7.5 7.5 0 1 1-2.2-5.3M19.5 4.5v4h-4",
  device: "M5 6.5a1 1 0 0 1 1-1h12a1 1 0 0 1 1 1V15H5zM3 18.5h18",
  bell: "M6.5 15.5V11a5.5 5.5 0 0 1 11 0v4.5l1.5 2H5zM10 20a2 2 0 0 0 4 0",
  user: "M12 12a3.75 3.75 0 1 0 0-7.5 3.75 3.75 0 0 0 0 7.5zM5 20a7 7 0 0 1 14 0",
  signOut: "M14.5 4.5H18a1 1 0 0 1 1 1v13a1 1 0 0 1-1 1h-3.5M10 8l-4 4 4 4M6 12h9.5",
  search: "M10.5 17a6.5 6.5 0 1 0 0-13 6.5 6.5 0 0 0 0 13zM15.5 15.5 20 20",
  copy: "M9 9h10v10H9zM5.5 15V5.5H15",
  send: "M12 19V5.5M6.5 11 12 5.5l5.5 5.5",
  pulse: "M3 12h4l2-5 4 10 2-5h6",
  card: "M3.5 6.5h17v11h-17zM3.5 10h17M7 14.5h4",
  stack: "M12 4 3.5 8.5 12 13l8.5-4.5zM3.5 12.5 12 17l8.5-4.5M3.5 16 12 20.5l8.5-4.5",
} as const;

export type IconName = keyof typeof PATHS;

export function Icon({ name, size = 24, className = "" }: { name: IconName; size?: number; className?: string }) {
  return (
    <svg
      className={`m-icon${className ? ` ${className}` : ""}`}
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={name === "more" ? 2.75 : 1.75}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
    >
      <path d={PATHS[name]} />
    </svg>
  );
}
