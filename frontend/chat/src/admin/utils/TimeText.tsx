import { formatDate, formatDateTime, formatExactTime, formatRecent, formatRelative, timeOf } from "./dateTime";

type TimeTextProps = {
  value: string | number | Date | null | undefined;
  // relative: "11 min ago" (default); dateTime: "13:31"; date: "".
  // recent: relative up to 7 days, then the date (list columns such as "Updated").
  mode?: "relative" | "dateTime" | "date" | "recent";
  fallback?: string;
  className?: string;
};

/** A moment in the UI's one format, with the exact time as tooltip. */
export function TimeText({ value, mode = "relative", fallback = "—", className }: TimeTextProps) {
  const time = timeOf(value);
  if (time === null) return <span className={className}>{fallback}</span>;
  const text =
    mode === "date" ? formatDate(time)
      : mode === "dateTime" ? formatDateTime(time)
        : mode === "recent" ? formatRecent(time)
          : formatRelative(time);
  return (
    <time className={className} dateTime={new Date(time).toISOString()} title={formatExactTime(time)}>
      {text}
    </time>
  );
}
