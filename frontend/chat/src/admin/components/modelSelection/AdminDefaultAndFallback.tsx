import { useCallback, useEffect, useState } from "react";

import { useAdminNavigation } from "../../adminNavigation";
import { takeAdminSection } from "../../config/adminPageSection";
import "../modelCatalog/modelCatalog.css";
import { PlatformEngineCard } from "../../../chat/engines/EngineCards";
import { LocalModelsCard } from "../localModels/LocalModelsCard";
import { ExplainTurn } from "./ExplainTurn";
import { loadSelection, saveOrder, saveTasks } from "./modelSelectionApi";
import {
  FALLBACK_CHOICES,
  addableModels,
  capabilityLabels,
  moveEntry,
  orderSubline,
  readSelectionPage,
  sameList,
  selectionErrorText,
  taskPayload,
} from "./modelSelectionContract";
import type { FallbackChoice, SelectionModel, SelectionPage } from "./modelSelectionContract";
import "./modelSelection.css";
import { LoadingState } from "../../../layout/LoadingState";
import { SegmentedTabs } from "../../../layout/SegmentedTabs";

const TABS = [
  { id: "order", label: "Platform order" },
  { id: "tasks", label: "Task models" },
  { id: "engine", label: "Coding engine" },
  { id: "local", label: "Local models" },
  { id: "explain", label: "Explain a turn" },
] as const;
type TabId = (typeof TABS)[number]["id"];

// Runtime → Models → Default & fallback: one platform order, what happens when a
// model fails, the model of each background task and the default coding engine (Claude Code or Codex). Each tab saves
// only its own settings.
export function AdminDefaultAndFallback() {
  const [page, setPage] = useState<SelectionPage | null>(null);
  const [loadError, setLoadError] = useState("");
  const [tab, setTab] = useState<TabId>(() => {
    const requested = takeAdminSection("modelOrder");
    return TABS.some((item) => item.id === requested) ? (requested as TabId) : "order";
  });

  const reload = useCallback(() => {
    loadSelection()
      .then((payload) => {
        setPage(readSelectionPage(payload));
        setLoadError("");
      })
      .catch(() => setLoadError("Default & fallback could not be loaded (platform admin role required)."));
  }, []);
  useEffect(reload, [reload]);
  const usesPage = tab === "order" || tab === "tasks";

  return (
    <div className="model-catalog" data-testid="default-and-fallback">
      <SegmentedTabs tabs={TABS.map((item) => ({ key: item.id, label: item.label }))} value={tab}
        onChange={(key) => setTab(key as TabId)} label="Defaults views" idPrefix="selection" size="small" testId="selection-tabs" />
      {loadError && usesPage ? <p className="admin-panel__error" role="alert">{loadError}</p> : null}
      {!page && !loadError && usesPage ? <LoadingState label="the platform order" /> : null}
      {page && tab === "order" ? <PlatformOrder key={JSON.stringify(page.order.map((m) => m.key))} page={page} onSaved={setPage} /> : null}
      {page && tab === "tasks" ? <TaskModels page={page} onSaved={setPage} /> : null}
      {tab === "engine" ? <PlatformEngineCard /> : null}
      {tab === "local" ? <LocalModelsCard /> : null}
      {tab === "explain" ? <ExplainTurn /> : null}
    </div>
  );
}

function OrderRow({ model, index, count, onMove, onRemove }: {
  model: SelectionModel; index: number; count: number;
  onMove: (step: -1 | 1) => void; onRemove: () => void;
}) {
  return (
    <div className="model-order__row" data-testid={`order-row-${model.key}`}>
      <span className="model-order__n">{index + 1}</span>
      <div>
        <div className="model-catalog__name">
          {model.displayName}
          {index === 0 ? <span className="model-catalog__tag"> · platform default</span> : null}
        </div>
        <div className="model-catalog__sub">{orderSubline(model)}</div>
      </div>
      <div className="model-catalog__chips">
        {capabilityLabels(model).map((label) => (
          <span key={label} className="admin-policy-chip admin-policy-chip--secondary">{label}</span>
        ))}
      </div>
      <div className="model-catalog__row-group">
        <button type="button" className="admin-users__row-btn" title="Move up" aria-label={`Move ${model.displayName} up`}
          disabled={index === 0} onClick={() => onMove(-1)}>↑</button>
        <button type="button" className="admin-users__row-btn" title="Move down" aria-label={`Move ${model.displayName} down`}
          disabled={index === count - 1} onClick={() => onMove(1)}>↓</button>
        <button type="button" className="admin-users__row-btn" title="Remove from the order"
          aria-label={`Remove ${model.displayName} from the order`} disabled={count === 1} onClick={onRemove}>✕</button>
      </div>
    </div>
  );
}

function PlatformOrder({ page, onSaved }: { page: SelectionPage; onSaved: (page: SelectionPage) => void }) {
  const initial = page.order.map((model) => model.key);
  const [order, setOrder] = useState<string[]>(initial);
  const [fallback, setFallback] = useState<FallbackChoice>(page.fallback);
  const [adding, setAdding] = useState("");
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState<{ error: boolean; text: string } | null>(null);
  const known = new Map([...page.models, ...page.order].map((model) => [model.key, model]));
  const addable = addableModels(page, order);
  const dirty = !sameList(order, initial) || fallback !== page.fallback;

  const save = async () => {
    setSaving(true);
    setMessage(null);
    try {
      onSaved(readSelectionPage(await saveOrder(order, fallback)));
      setMessage({ error: false, text: "Saved: platform order and fallback (only these two settings)." });
    } catch (failure) {
      setMessage({ error: true, text: selectionErrorText(failure) });
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="admin-panel__stack">
      {order.length ? (
        <div className="model-order" data-testid="platform-order">
          {order.map((key, index) => {
            const model = known.get(key);
            return model ? (
              <OrderRow key={key} model={model} index={index} count={order.length}
                onMove={(step) => setOrder((current) => moveEntry(current, index, step))}
                onRemove={() => setOrder((current) => current.filter((item) => item !== key))} />
            ) : null;
          })}
        </div>
      ) : (
        <p className="model-catalog__warn" role="status">
          No model is in the order, so nothing runs when nobody chose a model. Add an enabled model.
        </p>
      )}
      {addable.length ? (
        <OrderAdd addable={addable} adding={adding} setAdding={setAdding}
          onAdd={() => { setOrder((current) => [...current, adding]); setAdding(""); }} />
      ) : null}
      <FallbackChoices fallback={fallback} setFallback={setFallback} />
      <SaveMessage message={message} />
      <div className="model-catalog__row-group">
        <button type="button" className="admin-panel__action-btn admin-panel__action-btn--primary" data-testid="order-save"
          disabled={saving || !dirty || !order.length} onClick={() => void save()}>
          {saving ? "Saving…" : "Save order and fallback"}
        </button>
      </div>
    </div>
  );
}

function TaskModels({ page, onSaved }: { page: SelectionPage; onSaved: (page: SelectionPage) => void }) {
  const initial = Object.fromEntries(page.tasks.map((task) => [task.key, task.modelKey ?? ""]));
  const [tasks, setTasks] = useState<Record<string, string>>(initial);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState<{ error: boolean; text: string } | null>(null);
  const { openAdminTab } = useAdminNavigation();
  const platformDefault = page.order[0]?.displayName;
  // A task model is one of the platform order's models (it runs through that model's runtime).
  const ordered = page.order;
  const dirty = page.tasks.some((task) => (tasks[task.key] ?? "") !== (task.modelKey ?? ""));

  const save = async () => {
    setSaving(true);
    setMessage(null);
    try {
      onSaved(readSelectionPage(await saveTasks(taskPayload(tasks))));
      setMessage({ error: false, text: "Saved: task models." });
    } catch (failure) {
      setMessage({ error: true, text: selectionErrorText(failure) });
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="admin-panel__stack">
      <table className="admin-panel__table model-catalog__table" data-testid="task-models">
        <thead><tr><th>Task</th><th>Model</th><th>Workspace overrides</th></tr></thead>
        <tbody>
          {page.tasks.map((task) => (
            <TaskRow key={task.key} task={task} value={tasks[task.key] ?? ""} platformDefault={platformDefault} ordered={ordered}
              onChange={(value) => setTasks((current) => ({ ...current, [task.key]: value }))} />
          ))}
        </tbody>
      </table>
      <SaveMessage message={message} />
      <div className="model-catalog__row-group">
        <button type="button" className="admin-panel__action-btn admin-panel__action-btn--primary" data-testid="tasks-save"
          disabled={saving || !dirty} onClick={() => void save()}>
          {saving ? "Saving…" : "Save task models"}
        </button>
      </div>
      <div className="model-catalog__row-group">
        <button type="button" className="admin-panel__action-btn" onClick={() => openAdminTab("runtimePolicyLists")}>
          Open policy lists
        </button>
      </div>
    </div>
  );
}

type Message = { error: boolean; text: string } | null;

// What a save did, or why it was refused.
function SaveMessage({ message }: { message: Message }) {
  return message ? (
    <p className={message.error ? "admin-panel__error" : "admin-panel__success"} role={message.error ? "alert" : "status"}>
      {message.text}
    </p>
  ) : null;
}

// Adds an enabled model that is not in the order yet to its end.
function OrderAdd({ addable, adding, setAdding, onAdd }: {
  addable: SelectionModel[]; adding: string; setAdding: (key: string) => void; onAdd: () => void;
}) {
  return (
    <div className="model-catalog__row-group">
      <label className="admin-panel__field model-order__add">
        <span>Add to the order</span>
        <select value={adding} onChange={(event) => setAdding(event.target.value)} data-testid="order-add-select">
          <option value="">Choose an enabled model</option>
          {addable.map((model) => <option key={model.key} value={model.key}>{model.displayName} · {model.provider}</option>)}
        </select>
      </label>
      <button type="button" className="admin-panel__action-btn" disabled={!adding} data-testid="order-add"
        onClick={onAdd}>
        Add
      </button>
    </div>
  );
}

// What happens when a model fails: the next allowed model, or an error.
function FallbackChoices({ fallback, setFallback }: { fallback: FallbackChoice; setFallback: (choice: FallbackChoice) => void }) {
  return (
    <>
      <div className="admin-panel__section-header"><span>When a model fails</span></div>
      <div className="model-order__choices" role="radiogroup" aria-label="When a model fails">
        {FALLBACK_CHOICES.map((choice) => (
          <label key={choice.value} className="admin-option-card">
            <input type="radio" name="runtime-fallback" value={choice.value} checked={fallback === choice.value}
              onChange={() => setFallback(choice.value)} data-testid={`fallback-${choice.value}`} />
            <span className="admin-option-card__body">
              <span className="admin-option-card__title">{choice.title}</span>
              <span className="admin-option-card__desc">{choice.help}</span>
            </span>
          </label>
        ))}
      </div>
    </>
  );
}

// One background task with its model (one of the platform order's) and its Workspace overrides.
function TaskRow({ task, value, platformDefault, ordered, onChange }: {
  task: SelectionPage["tasks"][number]; value: string; platformDefault: string | undefined; ordered: SelectionModel[];
  onChange: (value: string) => void;
}) {
  return (
    <tr>
      <td data-label="Task">{task.label}</td>
      <td data-label="Model">
        <select className="admin-users__toolbar-select" aria-label={`Model for ${task.label}`}
          value={value} data-testid={`task-model-${task.key}`}
          onChange={(event) => onChange(event.target.value)}>
          <option value="">{platformDefault ? `Platform default (${platformDefault})` : "Platform default"}</option>
          {ordered.map((model) => <option key={model.key} value={model.key}>{model.displayName}</option>)}
        </select>
      </td>
      <td data-label="Overrides">
        {task.workspaceOverrides
          ? `${task.workspaceOverrides} ${task.workspaceOverrides === 1 ? "Workspace" : "Workspaces"}`
          : <span className="model-catalog__off">None</span>}
      </td>
    </tr>
  );
}
