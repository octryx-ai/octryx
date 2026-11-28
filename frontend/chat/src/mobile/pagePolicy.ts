// Untrusted page: without allow-same-origin its opaque origin cannot reach the app's cookies, storage, DOM or API.
// The policy goes first: a page can only tighten it, never loosen it.

export const PAGE_CSP = [
  "default-src 'none'",
  "script-src 'unsafe-inline' https://cdnjs.cloudflare.com https://cdn.jsdelivr.net https://unpkg.com https://cdn.tailwindcss.com",
  "style-src 'unsafe-inline' https://fonts.googleapis.com https://cdnjs.cloudflare.com https://cdn.jsdelivr.net https://unpkg.com",
  "font-src data: https://fonts.gstatic.com https://cdnjs.cloudflare.com https://cdn.jsdelivr.net",
  "img-src data: blob:",
  "media-src data: blob:",
  "connect-src 'none'",
  "frame-src 'none'",
  "object-src 'none'",
  "form-action 'none'",
  "base-uri 'none'",
].join("; ");

export function pageSrcDoc(html: string): string {
  return `<meta http-equiv="Content-Security-Policy" content="${PAGE_CSP}"><meta name="referrer" content="no-referrer">${html}`;
}
