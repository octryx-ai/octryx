import { DEFAULT_BRANDING } from "./defaultBranding";

type BrandingLike = (Partial<typeof DEFAULT_BRANDING> & { enabled?: boolean }) | null | undefined;

function pickBrandingValue(
  value: string | undefined,
  fallback: string,
): string {
  const normalized = value?.trim() ?? "";
  return normalized || fallback;
}

export function resolveBranding(branding?: BrandingLike) {
  return {
    app_name: pickBrandingValue(branding?.app_name, DEFAULT_BRANDING.app_name),
    logo_url: pickBrandingValue(branding?.logo_url, DEFAULT_BRANDING.logo_url),
    logo_svg: branding?.logo_svg?.trim() ?? DEFAULT_BRANDING.logo_svg,
    enabled: branding?.enabled === true,
  };
}
