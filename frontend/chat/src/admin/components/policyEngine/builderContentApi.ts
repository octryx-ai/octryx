import { readJson } from "../../utils/adminPanelHelpers";
import { POLICY_ENGINE_PATH } from "./policyEngineApi";

// The preview text is synthetic and never stored, logged or audited by the server.

export const loadContentDetectors = () => readJson<unknown>(`${POLICY_ENGINE_PATH}/content-detectors`);

export const previewContent = (text: string, mask: string[], maskStyle: string) =>
  readJson<unknown>(`${POLICY_ENGINE_PATH}/content-detectors/preview`, {
    method: "POST",
    body: JSON.stringify({ text, mask, ...(maskStyle ? { mask_style: maskStyle } : {}) }),
  });
