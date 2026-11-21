import { fieldLabel, secretRebindConfirmText, secretRebindSummary, SECRET_REBIND_REQUIRED } from "../secretRebind/secretRebindModel";
import { rebindFieldHint, rebindFieldRole } from "../secretRebind/secretRebindFlow";
import type { SecretRebindFlow } from "../secretRebind/secretRebindFlow";

// DOM of the secret_rebind_required refusal inside one /admin/tools config form. Every text goes in through
// textContent; the refusal carries field names only, so no value, URL or host can appear here.

export type RefusalHandlers = {
  onReenter: () => void;
  onConfirmStep: () => void;
  onConfirm: () => void;
  onBack: () => void;
};

const UI_ATTR = "data-rebind-ui";
const FIELD_CLASSES = ["tools-guard-field--attention", "tools-guard-field--error"];

function element<K extends keyof HTMLElementTagNameMap>(tag: K, className: string, text?: string): HTMLElementTagNameMap[K] {
  const node = document.createElement(tag);
  node.className = className;
  if (text !== undefined) node.textContent = text;
  node.setAttribute(UI_ATTR, "");
  return node;
}

function button(label: string, variant: "" | "primary" | "danger", onClick: () => void, disabled = false): HTMLButtonElement {
  const node = element("button", `tools-guard-btn${variant ? ` tools-guard-btn--${variant}` : ""}`, label);
  node.type = "button";
  node.disabled = disabled;
  node.addEventListener("click", onClick);
  return node;
}

// The element a field's note goes after: its own input, or the configuration JSON a target field lives in.
function fieldAnchor(form: HTMLFormElement, field: string): HTMLElement | null {
  const own = form.querySelector<HTMLElement>(`[name="${field}"]`);
  return own ?? form.querySelector<HTMLElement>('[name="config_json"]');
}

export function clearRefusal(form: HTMLFormElement): void {
  form.querySelectorAll(`[${UI_ATTR}]`).forEach((node) => node.remove());
  form.querySelectorAll(`.${FIELD_CLASSES.join(", .")}`).forEach((node) => node.classList.remove(...FIELD_CLASSES));
}

function renderFieldNotes(form: HTMLFormElement, flow: SecretRebindFlow<unknown>): void {
  const fields = [...flow.refusal.changedTargetFields, ...flow.refusal.keptFields];
  for (const field of fields) {
    const role = rebindFieldRole(flow, field);
    const anchor = fieldAnchor(form, field);
    if (!role || !anchor) continue;
    const tone = role === "missing_secret" ? "error" : "attention";
    if (anchor.getAttribute("name") === field) anchor.classList.add(`tools-guard-field--${tone}`);
    const prefix = anchor.getAttribute("name") === field ? "" : `${fieldLabel(field)}: `;
    anchor.insertAdjacentElement("afterend", element("p", `tools-guard-hint tools-guard-hint--${tone}`, prefix + rebindFieldHint(role, flow.step)));
  }
}

function renderPanel(flow: SecretRebindFlow<unknown>, busy: boolean, handlers: RefusalHandlers): HTMLElement {
  const { refusal, step } = flow;
  const panel = element("div", "tools-guard-refusal");
  panel.setAttribute("role", "alert");
  const head = element("div", "tools-guard-refusal__head");
  head.append(element("strong", "", "Secret rebind required"), element("code", "tools-guard-refusal__code", SECRET_REBIND_REQUIRED));
  panel.append(head, element("p", "tools-guard-refusal__text", secretRebindSummary(refusal)));
  const fields = element("dl", "tools-guard-refusal__fields");
  fields.append(
    element("dt", "", "Changed target"),
    element("dd", "", refusal.changedTargetFields.map(fieldLabel).join(", ") || "—"),
    element("dt", "", "Kept secret"),
    element("dd", "", refusal.keptFields.map(fieldLabel).join(", ") || "—"),
  );
  panel.append(fields);
  const actions = element("div", "tools-guard-refusal__actions");
  if (step === "choose") {
    actions.append(
      button("Send the stored secret to the new host…", "", handlers.onConfirmStep),
      button("Re-enter secret", "primary", handlers.onReenter),
    );
  } else if (step === "reenter") {
    panel.append(element("p", "tools-guard-refusal__text", `Enter a new value for ${refusal.keptFields.map(fieldLabel).join(", ")} above, then save or test again.`));
    if (flow.error) panel.append(element("p", "tools-guard-refusal__error", flow.error));
    actions.append(button("Back", "", handlers.onBack));
  } else {
    panel.append(element("p", "tools-guard-refusal__text tools-guard-refusal__text--strong", secretRebindConfirmText(refusal)));
    actions.append(
      button("Cancel", "", handlers.onBack, busy),
      button(busy ? "Sending…" : "Confirm: send the stored secret", "danger", handlers.onConfirm, busy),
    );
  }
  panel.append(actions);
  return panel;
}

export function renderRefusal(form: HTMLFormElement, flow: SecretRebindFlow<unknown>, busy: boolean, handlers: RefusalHandlers): void {
  clearRefusal(form);
  renderFieldNotes(form, flow);
  const slot = form.querySelector("[data-tool-config-actions]");
  const panel = renderPanel(flow, busy, handlers);
  if (slot) slot.insertAdjacentElement("beforebegin", panel);
  else form.append(panel);
}

export function renderFailure(form: HTMLFormElement, text: string): void {
  clearRefusal(form);
  const box = element("p", "tools-guard-refusal tools-guard-refusal--error", text);
  box.setAttribute("role", "alert");
  const slot = form.querySelector("[data-tool-config-actions]");
  if (slot) slot.insertAdjacentElement("beforebegin", box);
  else form.append(box);
}
