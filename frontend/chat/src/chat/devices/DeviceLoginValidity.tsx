import { useEffect, useState } from "react";

import { FormSection } from "../../layout/FormSection";
import { SidePanel } from "../../layout/SidePanel";
import { loadLoginValidity, saveLoginValidity } from "./devicesApi";

// Admin › Platform › Devices: how long a device login stays valid, for Macs and paired phones.
// `<n>h` or `<n>d`, from 1 hour to 365 days; "never" does not exist. The button shows the current value and opens
// the form in a side panel (design system rule 5).

const VALID = /^([1-9][0-9]{0,4})([hd])$/;

export function validityError(text: string): string {
  const match = VALID.exec(text.trim().toLowerCase());
  if (!match) return "Enter hours or days, for example 12h, 1d or 90d.";
  const hours = Number(match[1]) * (match[2] === "d" ? 24 : 1);
  if (hours < 1 || hours > 365 * 24) return "Between 1h and 365d.";
  return "";
}

export function DeviceLoginValidity() {
  const [value, setValue] = useState<string | null>(null);
  const [draft, setDraft] = useState("");
  const [open, setOpen] = useState(false);
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    loadLoginValidity().then(
      (body) =>
        setValue((body as { validity?: string } | null)?.validity ?? null),
      () => setValue(null),
    );
  }, []);

  const save = async () => {
    const problem = validityError(draft);
    setError(problem);
    if (problem) return;
    setSaving(true);
    try {
      const body = (await saveLoginValidity(draft.trim().toLowerCase())) as {
        validity?: string;
      } | null;
      if (!body?.validity) throw new Error("save");
      setValue(body.validity);
      setOpen(false);
    } catch {
      setError("Not saved. Try again.");
    } finally {
      setSaving(false);
    }
  };

  if (value === null) return null;
  return (
    <>
      <button
        type="button"
        className="admin-panel__action-btn"
        data-testid="device-login-validity"
        onClick={() => {
          setDraft(value);
          setError("");
          setOpen(true);
        }}
      >
        Device login valid for {value}
      </button>
      {open ? (
        <SidePanel
          title="Device login validity"
          size="narrow"
          onClose={() => setOpen(false)}
          testId="device-login-validity-panel"
          footer={
            <>
              <button
                type="button"
                className="admin-panel__action-btn"
                onClick={() => setOpen(false)}
              >
                Cancel
              </button>
              <button
                type="button"
                className="admin-panel__action-btn admin-panel__action-btn--primary"
                disabled={saving}
                onClick={() => void save()}
              >
                Save
              </button>
            </>
          }
        >
          <FormSection title="Macs and phones">
            <label htmlFor="device-login-validity-input">
              Valid for (1h to 365d)
            </label>
            <input
              id="device-login-validity-input"
              className="admin-panel__input"
              value={draft}
              onChange={(event) => setDraft(event.target.value)}
              placeholder="90d"
            />
            {error ? (
              <p className="work-area__error" role="alert">
                {error}
              </p>
            ) : null}
          </FormSection>
        </SidePanel>
      ) : null}
    </>
  );
}
