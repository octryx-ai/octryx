// Admin › Connections › Databases: the pause/resume and remove requests of the open database, over the page's setters.
import type { DatabaseCard } from "./databasePresenters";

type SetState<T> = (value: T) => void;

export async function togglePauseDatabase(
  connector: DatabaseCard,
  { readJson, setDatabaseConnectors, setBusy, setError }: {
    readJson: (url: string, init?: RequestInit) => Promise<any>;
    setDatabaseConnectors: (update: (current: DatabaseCard[]) => DatabaseCard[]) => void;
    setBusy: SetState<boolean>;
    setError: SetState<string | null>;
  },
) {
  setBusy(true);
  setError(null);
  try {
    const updated = await readJson(`/admin/chat/api/panel/database-connectors/${connector.id}`, {
      method: "PUT",
      body: JSON.stringify({ is_active: !connector.is_active }),
    });
    setDatabaseConnectors((current: DatabaseCard[]) =>
      current.map((item) => (item.id === connector.id ? { ...item, ...updated, health: item.health } : item)),
    );
  } catch (err) {
    setError(err instanceof Error ? err.message : "Not changed.");
  } finally {
    setBusy(false);
  }
}

export async function removeDatabase(
  connector: DatabaseCard,
  { handleDeleteDatabaseConnector, setRemoving, setBusy, setError }: {
    handleDeleteDatabaseConnector: (id: string) => Promise<void>;
    setRemoving: SetState<boolean>;
    setBusy: SetState<boolean>;
    setError: SetState<string | null>;
  },
) {
  setBusy(true);
  setError(null);
  try {
    await handleDeleteDatabaseConnector(connector.id);
    setRemoving(false);
  } catch (err) {
    setError(err instanceof Error ? err.message : "Not removed.");
  } finally {
    setBusy(false);
  }
}
