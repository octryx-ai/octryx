// Kept apart from the components for fast refresh.

export function elementCentre(root: HTMLElement | null, path: string): { x: number; y: number } | null {
  const scalerBox = root?.querySelector(".studio-scaler")?.getBoundingClientRect();
  const element = root?.querySelector(`[data-mock-path="${CSS.escape(path)}"]`)?.getBoundingClientRect();
  const frame = root?.querySelector(".studio-scaler") as HTMLElement | null;
  if (!scalerBox || !element || !frame) return null;
  const scale = scalerBox.width / (frame.offsetWidth || scalerBox.width);
  return { x: Math.round((element.left + element.width / 2 - scalerBox.left) / scale),
    y: Math.round((element.top + element.height / 2 - scalerBox.top) / scale) };
}
