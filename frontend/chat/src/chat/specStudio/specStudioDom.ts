// DOM helpers of the Spec Studio mock (kept apart from the components for fast refresh).

/** Where an element sits in the mock's own pixels (its centre): the pin of a note added from the list. */
export function elementCentre(root: HTMLElement | null, path: string): { x: number; y: number } | null {
  const scalerBox = root?.querySelector(".studio-scaler")?.getBoundingClientRect();
  const element = root?.querySelector(`[data-mock-path="${CSS.escape(path)}"]`)?.getBoundingClientRect();
  const frame = root?.querySelector(".studio-scaler") as HTMLElement | null;
  if (!scalerBox || !element || !frame) return null;
  const scale = scalerBox.width / (frame.offsetWidth || scalerBox.width);
  return { x: Math.round((element.left + element.width / 2 - scalerBox.left) / scale),
    y: Math.round((element.top + element.height / 2 - scalerBox.top) / scale) };
}
