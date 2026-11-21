// Pictures the person attaches on the phone (screenshots could not be sent): made
// smaller on the phone before they leave it (a screenshot stays readable at 1600 px), sent as JPEG; the platform
// checks the bytes again and allows at most MAX_PICTURES of at most 2 MB each.

export const MAX_PICTURES = 3;
const LIMIT_BYTES = 1_900_000;
const STEPS = [
  { side: 1600, quality: 0.85 },
  { side: 1280, quality: 0.75 },
  { side: 960, quality: 0.65 },
];

/** The longest side scaled down to ``side`` (never up). */
export function fitInside(width: number, height: number, side: number): { width: number; height: number } {
  const scale = Math.min(1, side / Math.max(width, height, 1));
  return { width: Math.max(1, Math.round(width * scale)), height: Math.max(1, Math.round(height * scale)) };
}

/** The base64 of a blob, without the ``data:…;base64,`` prefix. */
export function blobBase64(blob: Blob): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result).split(",", 2)[1] ?? "");
    reader.onerror = () => reject(reader.error ?? new Error("read_failed"));
    reader.readAsDataURL(blob);
  });
}

async function decode(file: Blob): Promise<{ source: CanvasImageSource; width: number; height: number }> {
  if (typeof createImageBitmap === "function") {
    const bitmap = await createImageBitmap(file);
    return { source: bitmap, width: bitmap.width, height: bitmap.height };
  }
  const url = URL.createObjectURL(file);
  try {
    const image = new Image();
    image.src = url;
    await image.decode();
    return { source: image, width: image.naturalWidth, height: image.naturalHeight };
  } finally {
    URL.revokeObjectURL(url);
  }
}

/** The picture as a JPEG small enough to send, as base64; throws ``picture_unreadable`` / ``picture_too_large``. */
export async function shrinkPicture(file: Blob): Promise<string> {
  let decoded;
  try {
    decoded = await decode(file);
  } catch {
    throw new Error("picture_unreadable");
  }
  for (const step of STEPS) {
    const size = fitInside(decoded.width, decoded.height, step.side);
    const canvas = document.createElement("canvas");
    canvas.width = size.width;
    canvas.height = size.height;
    const context = canvas.getContext("2d");
    if (!context) throw new Error("picture_unreadable");
    context.fillStyle = "#fff"; // a transparent screenshot area turns white, not black
    context.fillRect(0, 0, size.width, size.height);
    context.drawImage(decoded.source, 0, 0, size.width, size.height);
    const blob = await new Promise<Blob | null>((resolve) => canvas.toBlob(resolve, "image/jpeg", step.quality));
    if (blob && blob.size <= LIMIT_BYTES) return blobBase64(blob);
  }
  throw new Error("picture_too_large");
}
