import {
  formWithSecretRebindConfirmation,
  formWithoutSecretRebindConfirmation,
  parseSecretRebindRefusal,
} from "../secretRebind/secretRebindModel";
import { blockedReentry, flowAtStep, refusedFlow } from "../secretRebind/secretRebindFlow";
import type { SecretRebindFlow } from "../secretRebind/secretRebindFlow";
import { classifyToolsConfigResponse, failureText } from "./toolsConfigSubmit";
import { clearRefusal, renderFailure, renderRefusal } from "./toolsConfigRefusalView";

// The /admin/tools built-in tool config form (server-rendered, backend/app/web/templates/tools.html) posts its save
// and connection test through fetch, so the explicit `secret_rebind_required` refusal is shown next to the
// form instead of as raw JSON: re-enter the kept secret(s), or confirm in a second click that the stored secret may
// be sent to the new host (the refused post resent unchanged plus confirm_secret_rebind=true).

type RefusedPost = { action: string; body: URLSearchParams };
type FormFlow = SecretRebindFlow<RefusedPost>;

const FORM_SELECTOR = "form[data-tool-config-form]";
const flows = new WeakMap<HTMLFormElement, FormFlow>();
const busyForms = new WeakSet<HTMLFormElement>();

function fieldValues(form: HTMLFormElement, fields: string[]): Record<string, string> {
  const values: Record<string, string> = {};
  for (const field of fields) {
    const input = form.elements.namedItem(field);
    values[field] = input instanceof HTMLInputElement ? input.value : "";
  }
  return values;
}

function focusField(form: HTMLFormElement, field: string | undefined): void {
  const input = field ? form.elements.namedItem(field) : null;
  if (input instanceof HTMLInputElement) input.focus();
}

function setBusy(form: HTMLFormElement, busy: boolean): void {
  if (busy) busyForms.add(form);
  else busyForms.delete(form);
  form.querySelectorAll<HTMLButtonElement>('button[type="submit"]').forEach((node) => (node.disabled = busy));
}

function show(form: HTMLFormElement, flow: FormFlow | null): void {
  if (!flow) {
    flows.delete(form);
    clearRefusal(form);
    return;
  }
  flows.set(form, flow);
  renderRefusal(form, flow, busyForms.has(form), {
    onReenter: () => {
      show(form, flowAtStep(flow, "reenter"));
      focusField(form, flow.refusal.keptFields[0]);
    },
    onConfirmStep: () => show(form, flowAtStep(flow, "confirm")),
    onConfirm: () => void post(form, flow.body.action, formWithSecretRebindConfirmation(flow.body.body)),
    onBack: () => show(form, flowAtStep(flow, "choose")),
  });
}

function replacePage(html: string): void {
  const next = new DOMParser().parseFromString(html, "text/html").querySelector("main");
  const current = document.querySelector("main");
  if (next && current) current.replaceWith(next);
  else window.location.reload();
}

async function post(form: HTMLFormElement, action: string, body: URLSearchParams): Promise<void> {
  setBusy(form, true);
  const flow = flows.get(form);
  if (flow) show(form, flow);
  try {
    const response = await fetch(action, {
      method: "POST",
      body,
      credentials: "same-origin",
      headers: { Accept: "text/html, application/json" },
    });
    const outcome = classifyToolsConfigResponse(response.status, response.redirected, response.headers.get("content-type"));
    if (outcome === "navigate") {
      window.location.assign(response.url);
      return;
    }
    if (outcome === "replace_page") {
      replacePage(await response.text());
      return;
    }
    const payload: unknown = await response.json().catch(() => null);
    const refusal = outcome === "refused" ? parseSecretRebindRefusal(response.status, payload) : null;
    setBusy(form, false);
    if (refusal) {
      show(form, refusedFlow(refusal, { action, body: formWithoutSecretRebindConfirmation(body) }));
      return;
    }
    flows.delete(form);
    renderFailure(form, failureText(response.status, payload));
  } catch {
    setBusy(form, false);
    flows.delete(form);
    renderFailure(form, "The request failed: the server could not be reached.");
  }
}

function onSubmit(event: SubmitEvent): void {
  const form = event.target;
  if (!(form instanceof HTMLFormElement) || !form.matches(FORM_SELECTOR)) return;
  event.preventDefault();
  if (busyForms.has(form)) return;
  const flow = flows.get(form) ?? null;
  const blocked = flow ? blockedReentry(flow, fieldValues(form, flow.refusal.keptFields)) : null;
  if (blocked) {
    show(form, blocked);
    focusField(form, blocked.missing[0]);
    return;
  }
  const submitter = event.submitter;
  const action = submitter?.getAttribute("formaction") || form.getAttribute("action") || "";
  const data = new FormData(form, submitter ?? undefined);
  const body = new URLSearchParams();
  data.forEach((value, key) => {
    if (typeof value === "string") body.append(key, value);
  });
  void post(form, action, formWithoutSecretRebindConfirmation(body));
}

// Editing anything but a kept secret changes what was refused: the refusal and its confirm step no longer apply.
function onInput(event: Event): void {
  const target = event.target;
  if (!(target instanceof HTMLInputElement || target instanceof HTMLTextAreaElement)) return;
  const form = target.form;
  const flow = form ? flows.get(form) : undefined;
  if (!form || !flow) return;
  if (!flow.refusal.keptFields.includes(target.name)) show(form, null);
  else if (flow.error) show(form, { ...flow, error: null, missing: flow.missing.filter((name) => name !== target.name) });
}

export function installToolsConfigGuard(doc: Document): void {
  if (doc.documentElement.hasAttribute("data-tools-config-guard")) return;
  doc.documentElement.setAttribute("data-tools-config-guard", "");
  doc.addEventListener("submit", onSubmit);
  doc.addEventListener("input", onInput);
}

installToolsConfigGuard(document);
