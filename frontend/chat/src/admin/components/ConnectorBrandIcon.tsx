import { CONNECTOR_COLORS, CONNECTOR_ICONS } from "../config/adminPanelVisuals";
import { connectorMonogram, hasBrandGlyph } from "./connectorMonogram";
import "./connectorBrandIcon.css";

// The one brand tile for a connector or source kind: the real logo (simple-icons, via adminPanelVisuals) in its
// brand colour. Every kind without a brand glyph gets the same neutral monogram tile, labelled with its name.
export function ConnectorBrandIcon({ kind, label }: { kind: string; label: string }) {
  if (!hasBrandGlyph(kind, CONNECTOR_ICONS)) {
    return (
      <span className="connector-brand-icon connector-brand-icon--monogram" role="img" aria-label={label} title={label}>
        <span className="connector-brand-icon__initial" aria-hidden="true">{connectorMonogram(label)}</span>
      </span>
    );
  }
  return (
    <span className="connector-brand-icon" style={{ color: CONNECTOR_COLORS[kind] }} aria-hidden="true" data-brand={kind}>
      {CONNECTOR_ICONS[kind]}
    </span>
  );
}
