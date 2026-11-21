// Branding logo upload. SVG files are read as text and must pass the same
// sanitizer the chat shell uses before rendering inline SVG; PNG files become
// a data URL in logo_url (the backend stores logo_url as given and the shell
// renders it in an <img>). A logo_url always wins over logo_svg, so an upload
// clears the other field.
export const MAX_PNG_LOGO_BYTES = 256 * 1024;

export type LogoUploadResult =
  | { ok: true; logo_url: string; logo_svg: string }
  | { ok: false; error: string };

export function logoUploadKind(file: { name: string; type: string }): "svg" | "png" | null {
  const name = file.name.toLowerCase();
  if (file.type === "image/svg+xml" || name.endsWith(".svg")) return "svg";
  if (file.type === "image/png" || name.endsWith(".png")) return "png";
  return null;
}

export function svgLogoResult(
  markup: string,
  sanitize: (markup: string) => string | null,
): LogoUploadResult {
  const sanitized = sanitize(markup);
  if (!sanitized) {
    return {
      ok: false,
      error: "This SVG uses unsupported or unsafe content (scripts, external references, or more than 20,000 characters).",
    };
  }
  return { ok: true, logo_url: "", logo_svg: sanitized };
}

export function pngLogoResult(dataUrl: string, sizeBytes: number): LogoUploadResult {
  if (sizeBytes > MAX_PNG_LOGO_BYTES) {
    return { ok: false, error: "PNG logos must be 256 KB or smaller." };
  }
  if (!dataUrl.startsWith("data:image/png;base64,")) {
    return { ok: false, error: "The selected file is not a PNG image." };
  }
  return { ok: true, logo_url: dataUrl, logo_svg: "" };
}
