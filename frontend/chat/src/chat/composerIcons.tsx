// Icons of the chat composer: attach, voice, slash commands, mentions, canvas, send and its option menus.

export function AttachIcon() {
  return (
    <svg viewBox="0 0 20 20" aria-hidden="true">
      <path d="M7.25 10.75 11.9 6.1a2.8 2.8 0 0 1 3.95 3.95l-6.1 6.1a4.1 4.1 0 0 1-5.8-5.8l6.2-6.2" />
    </svg>
  );
}

export function TtsIndicatorIcon() {
  return (
    <svg
      viewBox="0 0 20 20"
      aria-hidden="true"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.8"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <path d="M4 7h3l4-3v12l-4-3H4V7zm9 .5a4 4 0 0 1 0 5" />
    </svg>
  );
}

export function VoiceInputIcon() {
  return (
    <svg viewBox="0 0 20 20" aria-hidden="true">
      <rect x="7" y="2" width="6" height="10" rx="3" />
      <path d="M4 10a6 6 0 0 0 12 0M10 16v2M7 18h6" />
    </svg>
  );
}

export function SlashCommandIcon() {
  return (
    <svg viewBox="0 0 20 20" aria-hidden="true">
      <path d="M13.75 3.75 6.25 16.25" />
    </svg>
  );
}

export function MentionIcon() {
  return (
    <svg viewBox="0 0 20 20" aria-hidden="true">
      <path d="M13.35 13.1a4.75 4.75 0 1 1 1.35-3.3v1.45a1.45 1.45 0 0 0 2.9 0V9.8a7.6 7.6 0 1 0-2.08 5.24" />
      <path d="M12.55 9.8a2.55 2.55 0 1 1-5.1 0 2.55 2.55 0 0 1 5.1 0Z" />
    </svg>
  );
}

export function CanvasIcon() {
  return (
    <svg
      viewBox="0 0 20 20"
      aria-hidden="true"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.6"
    >
      <rect x="2" y="2" width="16" height="16" rx="2" />
      <path d="M5 13l3-3 2 2 3-4 2 2" />
    </svg>
  );
}

export function SendIcon() {
  return (
    <svg viewBox="0 0 20 20" aria-hidden="true">
      <path d="M4.25 9.9 15.4 4.95c.62-.28 1.28.38 1 1l-4.95 11.15c-.29.65-1.24.61-1.47-.07l-1.37-4.06-4.06-1.37c-.68-.23-.72-1.18-.07-1.47Z" />
      <path d="M8.6 12.95 16.1 5.45" />
    </svg>
  );
}

export function DownArrowIcon() {
  return (
    <svg viewBox="0 0 20 20" aria-hidden="true">
      <path d="M10 4.5v11" />
      <path d="M5.5 11l4.5 4.5 4.5-4.5" />
    </svg>
  );
}

export function MoreActionsIcon() {
  return (
    <svg viewBox="0 0 20 20" aria-hidden="true">
      <circle cx="5" cy="10" r="1.15" />
      <circle cx="10" cy="10" r="1.15" />
      <circle cx="15" cy="10" r="1.15" />
    </svg>
  );
}

export function OptionsIcon() {
  return (
    <svg viewBox="0 0 20 20" aria-hidden="true">
      <path d="M3.5 6.5h13" />
      <path d="M3.5 13.5h13" />
      <circle cx="8" cy="6.5" r="1.7" />
      <circle cx="13" cy="13.5" r="1.7" />
    </svg>
  );
}
