

const SAFE_ADMIN_ERROR = /^[A-Za-z0-9 ,.:;_'()[\]{}/-]{1,240}$/;

/** A proxy in front of the Admin API may answer anything, so only a short, URL-free, narrow-charset string is shown. */
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
