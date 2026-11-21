import { useState, type ChangeEvent } from "react";

import { sanitizeInlineSvgMarkup } from "../../chat/logoSvgSanitizer";
import { DEFAULT_BRANDING } from "../../chat/defaultBranding";
import {
  logoUploadKind,
  pngLogoResult,
  svgLogoResult,
  type LogoUploadResult,
} from "./brandingLogoUpload";

type BrandingConfig = {
  app_name: string;
  logo_url: string;
  logo_svg: string;
};

type AdminBrandingTabCtx = {
  brandingConfig: BrandingConfig | null;
  setBrandingConfig: (
    value:
      | BrandingConfig
      | null
      | ((value: BrandingConfig | null) => BrandingConfig | null),
  ) => void;
  brandingFormError: string | null;
  brandingFormSaved: boolean;
  brandingFormLoading: boolean;
  onSaveBranding: () => void | Promise<void>;
};

type AdminBrandingTabProps = {
  ctx: Record<string, unknown>;
};

type SetBranding = AdminBrandingTabCtx["setBrandingConfig"];
type UploadMessage = { tone: "ok" | "error"; text: string } | null;

const readDataUrl = (file: File) => new Promise<string>((resolve, reject) => {
  const reader = new FileReader();
  reader.onload = () => resolve(String(reader.result || ""));
  reader.onerror = () => reject(reader.error);
  reader.readAsDataURL(file);
}).catch(() => "");

// A picked logo file: an SVG is sanitized, a PNG read as a data URL; either replaces the logo URL and SVG code.
function useLogoUpload(setBrandingConfig: SetBranding) {
  const [uploadMessage, setUploadMessage] = useState<UploadMessage>(null);

  const applyUpload = (result: LogoUploadResult, fileName: string) => {
    if (!result.ok) {
      setUploadMessage({ tone: "error", text: result.error });
      return;
    }
    setBrandingConfig((value) => ({
      ...(value || DEFAULT_BRANDING),
      logo_url: result.logo_url,
      logo_svg: result.logo_svg,
    }));
    setUploadMessage({ tone: "ok", text: `${fileName} loaded. Save branding to apply it.` });
  };

  const handleLogoFile = async (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file) return;
    const kind = logoUploadKind(file);
    if (kind === "svg") {
      applyUpload(svgLogoResult(await file.text(), sanitizeInlineSvgMarkup), file.name);
      return;
    }
    if (kind === "png") {
      const dataUrl = await readDataUrl(file);
      applyUpload(pngLogoResult(dataUrl, file.size), file.name);
      return;
    }
    setUploadMessage({ tone: "error", text: "Upload an SVG or PNG file." });
  };
  return { uploadMessage, handleLogoFile };
}

type FieldsProps = { brandingConfig: BrandingConfig | null; setBrandingConfig: SetBranding };

function BrandingNameAndUpload({ brandingConfig, setBrandingConfig }: FieldsProps) {
  const { uploadMessage, handleLogoFile } = useLogoUpload(setBrandingConfig);
  return (
    <>
      <label className="admin-form-field admin-form-grid__full">
        <span className="admin-form-field__label">App name</span>
        <input
          className="admin-panel__form-input"
          type="text"
          value={brandingConfig?.app_name ?? ""}
          onChange={(event) =>
            setBrandingConfig((value) =>
              value
                ? { ...value, app_name: event.target.value }
                : { ...DEFAULT_BRANDING, app_name: event.target.value },
            )
          }
          placeholder="Octryx"
        />
        <span className="admin-form-help">
          Shown in the sidebar, workspace header and admin panel.
        </span>
      </label>
      <label className="admin-form-field admin-form-grid__full">
        <span className="admin-form-field__label">Upload logo</span>
        <input
          className="admin-panel__form-input"
          type="file"
          accept=".svg,image/svg+xml,.png,image/png"
          onChange={(event) => void handleLogoFile(event)}
        />
        <span className="admin-form-help">
          SVG (sanitized, up to 20,000 characters) or PNG (up to 256 KB).
          An upload replaces the logo URL or SVG code below.
        </span>
        {uploadMessage ? (
          <span className={uploadMessage.tone === "error" ? "admin-panel__form-error" : "admin-form-help"} role={uploadMessage.tone === "error" ? "alert" : undefined}>
            {uploadMessage.text}
          </span>
        ) : null}
      </label>
    </>
  );
}

function BrandingLogoFields({ brandingConfig, setBrandingConfig }: FieldsProps) {
  return (
    <>
      <label className="admin-form-field">
        <span className="admin-form-field__label">Logo URL</span>
        <input
          className="admin-panel__form-input"
          type="url"
          value={brandingConfig?.logo_url ?? ""}
          onChange={(event) =>
            setBrandingConfig((value) =>
              value
                ? { ...value, logo_url: event.target.value }
                : { ...DEFAULT_BRANDING, logo_url: event.target.value },
            )
          }
          placeholder="https://example.com/logo.png"
        />
        <span className="admin-form-help">
          A hosted PNG or SVG. When set, it wins over the SVG code.
        </span>
      </label>
      <label className="admin-form-field">
        <span className="admin-form-field__label">Logo SVG</span>
        <textarea
          className="admin-panel__form-input branding-editor__textarea"
          rows={6}
          value={brandingConfig?.logo_svg ?? ""}
          onChange={(event) =>
            setBrandingConfig((value) =>
              value
                ? { ...value, logo_svg: event.target.value }
                : { ...DEFAULT_BRANDING, logo_svg: event.target.value },
            )
          }
          placeholder="<svg>...</svg>"
        />
        <span className="admin-form-help">
          Inline SVG is ideal for crisp dark-theme branding. Invalid or
          unsafe SVG is rejected on save.
        </span>
      </label>
    </>
  );
}

function BrandingPreview({ brandingConfig }: { brandingConfig: BrandingConfig | null }) {
  const safePreviewLogoSvg = brandingConfig?.logo_svg
    ? sanitizeInlineSvgMarkup(brandingConfig.logo_svg)
    : null;
  return (
    <div className="admin-form-field">
      <span className="admin-form-field__label">Preview</span>
      <div className="branding-preview-card">
        <div className="branding-preview-card__mark">
          {brandingConfig?.logo_url ? (
            <img
              src={brandingConfig.logo_url}
              alt="logo"
              className="branding-preview-card__asset"
            />
          ) : safePreviewLogoSvg ? (
            <span
              dangerouslySetInnerHTML={{ __html: safePreviewLogoSvg }}
              className="branding-preview-card__asset branding-preview-card__asset--svg"
            />
          ) : (
            <svg
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="1.8"
              strokeLinecap="round"
              strokeLinejoin="round"
              className="branding-preview-card__fallback-icon"
            >
              <path d="M12 2L2 7l10 5 10-5-10-5zM2 17l10 5 10-5M2 12l10 5 10-5" />
            </svg>
          )}
        </div>
        <div className="branding-preview-card__copy">
          <div className="branding-preview-card__title">
            {brandingConfig?.app_name || "Octryx"}
          </div>
          <div className="branding-preview-card__subtitle">Workspace</div>
        </div>
      </div>
    </div>
  );
}

export function AdminBrandingTab({ ctx }: AdminBrandingTabProps) {
  const {
    brandingConfig,
    setBrandingConfig,
    brandingFormError,
    brandingFormSaved,
    brandingFormLoading,
    onSaveBranding,
  } = ctx as AdminBrandingTabCtx;

  return (
    <div className="branding-editor">
      <div className="admin-panel__section-header">
        <span>Branding</span>
      </div>
      <div className="admin-panel__stack">
        <div className="admin-form-grid">
          <BrandingNameAndUpload brandingConfig={brandingConfig} setBrandingConfig={setBrandingConfig} />
          <BrandingLogoFields brandingConfig={brandingConfig} setBrandingConfig={setBrandingConfig} />
        </div>

        <BrandingPreview brandingConfig={brandingConfig} />
        {brandingFormError ? (
          <div className="admin-panel__error">{brandingFormError}</div>
        ) : null}
        {brandingFormSaved ? (
          <div className="admin-success">Saved successfully.</div>
        ) : null}
        <button
          type="button"
          className="admin-panel__action-btn admin-panel__action-btn--primary"
          disabled={brandingFormLoading}
          onClick={() => void onSaveBranding()}
        >
          {brandingFormLoading ? "Saving..." : "Save branding"}
        </button>
      </div>
    </div>
  );
}
