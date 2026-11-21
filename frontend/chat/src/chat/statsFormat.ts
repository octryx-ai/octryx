// Number, percent and cost formatting of the chat statistics panel.

export function formatTokenCount(value: number) {
  return new Intl.NumberFormat("de-CH").format(value);
}

export function formatPercent(value: number) {
  if (!Number.isFinite(value) || value <= 0) {
    return "0%";
  }
  return `${Math.round(value * 100)}%`;
}

export function formatSignedPercent(value: number) {
  if (!Number.isFinite(value) || value === 0) {
    return "0%";
  }
  const sign = value > 0 ? "+" : "";
  return `${sign}${Math.round(value * 100)}%`;
}

export function formatSignedTokenCount(value: number) {
  if (!Number.isFinite(value) || value === 0) {
    return "0";
  }
  const sign = value > 0 ? "+" : "";
  return `${sign}${formatTokenCount(Math.round(value))}`;
}

export function formatCost(value: number | null | undefined) {
  const cost = Number(value || 0);
  return new Intl.NumberFormat("de-CH", {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: cost > 0 && cost < 0.01 ? 4 : 2,
    maximumFractionDigits: cost > 0 && cost < 0.01 ? 6 : 2,
  }).format(cost);
}
