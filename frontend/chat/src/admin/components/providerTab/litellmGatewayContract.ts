

const SAFE_ADMIN_ERROR = /^[A-Za-z0-9 ,.:;_'()[\]{}/-]{1,240}$/;

/**
 * Bound an admin error before it reaches the screen.
 *
 * The governed Admin API answers with fixed messages, but a gateway or proxy in
 * front of it does not have to. Only a short, narrow-charset string that carries
 * no URL and no userinfo is shown; anything else collapses to fixed copy, so a
 * remote response body, endpoint or auth header can never be rendered.
 */
export function boundedAdminErrorText(
  error: unknown,
  fallback: string,
): string {
  const message = error instanceof Error ? error.message.trim() : "";
  if (!message || message.includes("://") || message.includes("@")) {
    return fallback;
  }
  return SAFE_ADMIN_ERROR.test(message) ? message : fallback;
}
