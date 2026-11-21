import { readJson } from "../../utils/adminPanelHelpers";
import { POLICY_ENGINE_PATH } from "./policyEngineApi";

// The builder's content-routing calls (backend `api/routes/policy_engine_detectors.py`). The preview text is
// synthetic, answered in the request and never stored, logged or audited by the server.

/** Built-in and custom detectors of the working version (open draft, else published). */
export const loadContentDetectors = () => readJson<unknown>(`${POLICY_ENGINE_PATH}/content-detectors`);

/** What the detectors find in `text`; `mask` are the detectors to mask, `maskStyle` the policy's style. */
export const previewContent = (text: string, mask: string[], maskStyle: string) =>
  readJson<unknown>(`${POLICY_ENGINE_PATH}/content-detectors/preview`, {
    method: "POST",
    body: JSON.stringify({ text, mask, ...(maskStyle ? { mask_style: maskStyle } : {}) }),
  });
