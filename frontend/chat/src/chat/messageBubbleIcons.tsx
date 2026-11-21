export function TraceIcon() {
  return (
    <svg viewBox="0 0 20 20" aria-hidden="true">
      <path d="M4.5 15.5h3V10h3v5.5h3V6h3" />
      <path d="M13.5 6h3v3" />
    </svg>
  );
}

export function ThumbUpIcon() {
  return (
    <svg viewBox="0 0 20 20" aria-hidden="true">
      <path d="M8 9.25V16.25" />
      <path d="M8 9.25 10.75 3.75c.7 0 1.25.55 1.25 1.25v2h2.75c.83 0 1.5.67 1.5 1.5 0 .13-.02.26-.05.38l-1.1 5.5c-.14.69-.74 1.19-1.44 1.19H8" />
      <path d="M4 9.25h4v7H4z" />
    </svg>
  );
}

export function ThumbDownIcon() {
  return (
    <svg viewBox="0 0 20 20" aria-hidden="true">
      <path d="M12 10.5v5.75" />
      <path d="M12 10.5 9.6 15.2c-.26.52-.8.85-1.38.85-.68 0-1.22-.54-1.22-1.22V13H4.6c-.9 0-1.59-.8-1.46-1.7l.72-4.8c.11-.74.75-1.3 1.5-1.3H12" />
      <path d="M16 10.5h-4v-6.8h4z" />
    </svg>
  );
}

export function ThinkingDots() {
  return (
    <div className="thinking-indicator" aria-live="polite">
      <span className="thinking-indicator__label">Thinking</span>
      <span className="thinking-indicator__dots">
        <i />
        <i />
        <i />
      </span>
    </div>
  );
}

export function ThinkingIcon() {
  return (
    <svg viewBox="0 0 20 20" aria-hidden="true">
      <path d="M10 3.5a5.5 5.5 0 0 0-3.55 9.7c.42.37.8.87.93 1.4l.12.4h5l.12-.4c.13-.53.5-1.03.92-1.4A5.5 5.5 0 0 0 10 3.5Z" />
      <path d="M8 16.25h4" />
      <path d="M8.6 18h2.8" />
    </svg>
  );
}

export function PerformanceIcon() {
  return (
    <svg viewBox="0 0 20 20" aria-hidden="true">
      <path d="M4 15.5h12" />
      <path d="M5.5 13V9.5" />
      <path d="M10 13V6.5" />
      <path d="M14.5 13V4.5" />
    </svg>
  );
}

export function CopyIcon() {
  return (
    <svg viewBox="0 0 20 20" aria-hidden="true">
      <rect x="6.5" y="6.5" width="9" height="10" rx="1.5" />
      <path d="M4.5 12.5V4.8c0-.72.58-1.3 1.3-1.3h7.7" />
    </svg>
  );
}

export function RetryIcon() {
  return (
    <svg viewBox="0 0 20 20" aria-hidden="true">
      <path d="M6 6.5v4h4" />
      <path d="M6.4 10.5a5 5 0 1 0 1.1-3.4" />
    </svg>
  );
}

export function ReuseIcon() {
  return (
    <svg viewBox="0 0 20 20" aria-hidden="true">
      <path d="M4.75 14.25h10.5" />
      <path d="M4.75 10h10.5" />
      <path d="M4.75 5.75h6.5" />
      <path d="M13 4.25 15.25 6.5 13 8.75" />
    </svg>
  );
}

export function MultilineText({
  value,
  className = "tool-inline__pre",
}: {
  value: string;
  className?: string;
}) {
  if (!value.trim()) {
    return null;
  }
  return <pre className={className}>{value}</pre>;
}
