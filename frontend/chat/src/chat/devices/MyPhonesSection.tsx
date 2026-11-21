import { useCallback, useEffect, useState } from "react";

import { loadMyPhones, revokePhone } from "./devicesApi";
import { relativeTime } from "./devicesModel";

// My settings › Devices: the person's paired phones (Octryx Mobile) with last use and when the
// login ends; revoking signs the phone out on its next request.

type Phone = {
  id: string;
  name: string;
  createdAt: string;
  lastSeenAt: string | null;
  expiresAt: string;
  current: boolean;
};

export function readPhones(raw: unknown): Phone[] {
  const items =
    raw && typeof raw === "object" ? (raw as { items?: unknown }).items : null;
  if (!Array.isArray(items)) return [];
  return items.flatMap((item) => {
    const row =
      item && typeof item === "object" ? (item as Record<string, unknown>) : {};
    if (typeof row.id !== "string" || typeof row.name !== "string") return [];
    return [
      {
        id: row.id,
        name: row.name,
        createdAt: String(row.created_at ?? ""),
        lastSeenAt:
          typeof row.last_seen_at === "string" ? row.last_seen_at : null,
        expiresAt: String(row.login_expires_at ?? ""),
        current: row.this_device === true,
      },
    ];
  });
}

const day = (iso: string) => {
  const at = Date.parse(iso);
  return Number.isNaN(at)
    ? "—"
    : new Date(at).toLocaleDateString(undefined, {
        day: "numeric",
        month: "short",
        year: "numeric",
      });
};

export function MyPhonesSection() {
  const [phones, setPhones] = useState<Phone[] | null>(null);
  const [problem, setProblem] = useState("");

  const load = useCallback(async () => {
    try {
      setPhones(readPhones(await loadMyPhones()));
      setProblem("");
    } catch {
      setProblem("Your phones could not be loaded.");
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const revoke = async (id: string) => {
    try {
      await revokePhone(id);
      await load();
    } catch {
      setProblem("The phone was not revoked. Try again.");
    }
  };

  if (phones === null && !problem) return null;
  return (
    <section data-testid="my-phones">
      <div className="admin-panel__section-header">
        <span>Phones</span>
      </div>
      {problem ? (
        <p className="work-area__error" role="alert">
          {problem}
        </p>
      ) : null}
      {phones && phones.length === 0 ? (
        <p className="admin-panel__hint">
          No phone is connected. On your Mac: octryx mobile pair.
        </p>
      ) : null}
      {phones && phones.length > 0 ? (
        <table className="admin-panel__table">
          <thead>
            <tr>
              <th>Phone</th>
              <th>Paired</th>
              <th>Last used</th>
              <th>Valid until</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {phones.map((phone) => (
              <tr key={phone.id}>
                <td data-label="Phone">
                  {phone.name}
                  {phone.current ? " (this phone)" : ""}
                </td>
                <td data-label="Paired" className="admin-panel__cell--muted">
                  {day(phone.createdAt)}
                </td>
                <td data-label="Last used" className="admin-panel__cell--muted">
                  {relativeTime(phone.lastSeenAt)}
                </td>
                <td data-label="Valid until">{day(phone.expiresAt)}</td>
                <td>
                  <button
                    type="button"
                    className="admin-panel__action-btn"
                    onClick={() => void revoke(phone.id)}
                  >
                    Revoke
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : null}
    </section>
  );
}
