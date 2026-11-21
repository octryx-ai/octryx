import { useState } from "react";
import type { PanelScheduler } from "../types/projectQualityTypes.design";
import type { PanelTaskStepRow } from "../components/taskTypes";

export function useAdminWorkflowState() {
  const [schedulers, setSchedulers] = useState<PanelScheduler[]>([]);
  const [showSchedulerForm, setShowSchedulerForm] = useState(false);
  const [editingScheduler, setEditingScheduler] =
    useState<PanelScheduler | null>(null);
  const [schedulerFormName, setSchedulerFormName] = useState("");
  const [schedulerFormDesc, setSchedulerFormDesc] = useState("");
  const [schedulerFormCron, setSchedulerFormCron] = useState("");
  const [schedulerFormTaskId, setSchedulerFormTaskId] = useState("");
  const [schedulerFormLoading, setSchedulerFormLoading] = useState(false);
  const [schedulerFormError, setSchedulerFormError] = useState<string | null>(
    null,
  );

  const [taskSteps, setTaskSteps] = useState<Record<string, PanelTaskStepRow[]>>(
    {},
  );
  const [expandedSteps, setExpandedSteps] = useState<string | null>(null);
  const [showStepForm, setShowStepForm] = useState<string | null>(null);
  const [editingStep, setEditingStep] = useState<PanelTaskStepRow | null>(null);
  const [stepFormName, setStepFormName] = useState("Step");
  const [stepFormType, setStepFormType] = useState("analysis");
  const [stepFormConnector, setStepFormConnector] = useState("");
  const [stepFormConnectorAction, setStepFormConnectorAction] = useState("");
  const [stepFormInstructions, setStepFormInstructions] = useState("");
  const [stepFormMaxFix, setStepFormMaxFix] = useState(2);
  const [stepFormTimeout, setStepFormTimeout] = useState(300);
  const [stepFormAgentId, setStepFormAgentId] = useState("");
  const [stepFormContextFields, setStepFormContextFields] = useState("");
  const [stepFormConnectorParams, setStepFormConnectorParams] = useState("");
  const [stepFormLoading, setStepFormLoading] = useState(false);
  const [stepFormError, setStepFormError] = useState<string | null>(null);

  return {
    editingScheduler,
    setEditingScheduler,
    editingStep,
    setEditingStep,
    expandedSteps,
    setExpandedSteps,
    schedulerFormCron,
    setSchedulerFormCron,
    schedulerFormDesc,
    setSchedulerFormDesc,
    schedulerFormError,
    setSchedulerFormError,
    schedulerFormLoading,
    setSchedulerFormLoading,
    schedulerFormName,
    setSchedulerFormName,
    schedulerFormTaskId,
    setSchedulerFormTaskId,
    schedulers,
    setSchedulers,
    showSchedulerForm,
    setShowSchedulerForm,
    showStepForm,
    setShowStepForm,
    stepFormAgentId,
    setStepFormAgentId,
    stepFormConnector,
    setStepFormConnector,
    stepFormConnectorAction,
    setStepFormConnectorAction,
    stepFormConnectorParams,
    setStepFormConnectorParams,
    stepFormContextFields,
    setStepFormContextFields,
    stepFormError,
    setStepFormError,
    stepFormInstructions,
    setStepFormInstructions,
    stepFormLoading,
    setStepFormLoading,
    stepFormMaxFix,
    setStepFormMaxFix,
    stepFormName,
    setStepFormName,
    stepFormTimeout,
    setStepFormTimeout,
    stepFormType,
    setStepFormType,
    taskSteps,
    setTaskSteps,
  };
}
