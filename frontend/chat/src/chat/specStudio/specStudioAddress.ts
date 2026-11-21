import type { DataView, Device, Theme } from "./specStudioModel";

// The Spec Studio's address: a full-width Work view, `?area=work&work_view=spec_studio&run_id=…`.
// With `render=<screen>` it shows only that screen's mock (device, theme, data, version): the baseline image hands_on
// and the story review take; still behind the login like every page.

export const SPEC_STUDIO_VIEW = "spec_studio";

export type SpecStudioAddress = {
  runId: string;
  render: { screen: string; device: Device; theme: Theme; data: DataView; version: number | null } | null;
};

export function specStudioAddress(search: string): SpecStudioAddress | null {
  const params = new URLSearchParams(search);
  const runId = params.get("run_id")?.trim() ?? "";
  if (params.get("area") !== "work" || params.get("work_view") !== SPEC_STUDIO_VIEW || !runId) return null;
  const screen = params.get("render")?.trim() ?? "";
  if (!screen) return { runId, render: null };
  const version = Number(params.get("version"));
  return {
    runId,
    render: {
      screen,
      device: params.get("device") === "phone" ? "phone" : "desktop",
      theme: params.get("theme") === "dark" ? "dark" : "light",
      data: params.get("data") === "empty" ? "empty" : "filled",
      version: Number.isInteger(version) && version > 0 ? version : null,
    },
  };
}

/** The Studio's address for a run (the link on the run's decision card). */
export function specStudioHref(runId: string): string {
  return `/chat?area=work&work_view=${SPEC_STUDIO_VIEW}&run_id=${encodeURIComponent(runId)}`;
}

export type SpecStudioSummary = { version: number; open_points: number; frozen: boolean; approved: number };

export function specStudioLinkText(summary: SpecStudioSummary): string {
  if (summary.frozen) return `Spec v${summary.approved} approved: open the Spec Studio`;
  if (summary.open_points) return `Open the Spec Studio (${summary.open_points} open point${summary.open_points === 1 ? "" : "s"})`;
  return "Review and approve the spec in the Spec Studio";
}
