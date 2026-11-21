// The workspace brand mark: the configured logo image or inline SVG, else the fallback label.
import { sanitizeInlineSvgMarkup } from "./logoSvgSanitizer";
import { resolveBranding } from "./branding";

type Branding = {
  app_name: string;
  logo_url: string;
  logo_svg: string;
};

export function BrandGlyph({
  branding,
  fallbackLabel,
}: {
  branding?: Branding;
  fallbackLabel: string;
}) {
  const effectiveBranding = resolveBranding(branding);
  const safeLogoSvg = effectiveBranding.logo_svg
    ? sanitizeInlineSvgMarkup(effectiveBranding.logo_svg)
    : null;

  if (effectiveBranding.logo_url) {
    return (
      <img src={effectiveBranding.logo_url} alt="" className="brand__image" />
    );
  }
  if (safeLogoSvg) {
    return (
      <span
        className="brand__svg"
        dangerouslySetInnerHTML={{ __html: safeLogoSvg }}
      />
    );
  }
  return <span className="brand__fallback">{fallbackLabel}</span>;
}
