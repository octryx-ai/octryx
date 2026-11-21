// Builds the app.diagrams.net deep link for opening a diagram in the full editor.
// Mirrors the backend reference implementation (`_drawio_create_url` in
// backend/app/web/routers/chat_main.py): the XML is URI-encoded, raw-deflated,
// base64-encoded, and wrapped in draw.io's `#create=` JSON payload.

const DRAWIO_APP_BASE =
  "https://app.diagrams.net/?grid=0&pv=0&border=10&edit=_blank";

async function deflateRaw(data: Uint8Array): Promise<Uint8Array> {
  const stream = new Blob([data as BlobPart])
    .stream()
    .pipeThrough(new CompressionStream("deflate-raw"));
  return new Uint8Array(await new Response(stream).arrayBuffer());
}

function toBase64(bytes: Uint8Array): string {
  let binary = "";
  const chunkSize = 0x8000;
  for (let i = 0; i < bytes.length; i += chunkSize) {
    binary += String.fromCharCode(...bytes.subarray(i, i + chunkSize));
  }
  return btoa(binary);
}

export function supportsDrawioEditorUrl(): boolean {
  return typeof CompressionStream === "function";
}

export async function buildDrawioEditorUrl(xml: string): Promise<string> {
  const compressed = await deflateRaw(
    new TextEncoder().encode(encodeURIComponent(xml)),
  );
  const payload = encodeURIComponent(
    JSON.stringify({ type: "xml", compressed: true, data: toBase64(compressed) }),
  );
  return `${DRAWIO_APP_BASE}#create=${payload}`;
}
