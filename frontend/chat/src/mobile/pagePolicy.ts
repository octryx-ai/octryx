// A page a session made (HTML, SVG, an Office preview) shown on the phone (open artifacts such as HTML
// on the phone, so designs can be seen there too).
//
// The page is untrusted: a session wrote it, and a ticket or a web page may have steered that session. So it never
// runs as the app:
// - `sandbox="allow-scripts"` without `allow-same-origin`: the page gets an opaque origin, so it can't reach the
//   app's cookies, storage, DOM or API, can't navigate the app, and can't open pop-ups or submit forms;
// - a Content-Security-Policy is put first in the document; a policy can only be tightened by the page, never
//   loosened. It allows no network requests (`connect-src 'none'`), no frames or forms, and pictures only from inside
//   the page. Scripts, styles and fonts load only inline or from the common CDNs that design pages use.

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

/** The page with the policy as its very first element (the parser moves it into <head>, ahead of the page's own). */
export function pageSrcDoc(html: string): string {
  return `<meta http-equiv="Content-Security-Policy" content="${PAGE_CSP}"><meta name="referrer" content="no-referrer">${html}`;
}
