// Action step editor form: name, type, connector, instructions and runtime, with the type-specific fields.
import { useEffect, useRef } from "react";
import { AdminTaskStepTypeFields } from "./AdminTaskStepTypeFields";
import {
  StepConnectorFields,
  StepFormActions,
  StepFormHeader,
  StepInstructionsAndRuntimeFields,
  StepNameAndTypeFields,
  type AdminTaskStepFormProps,
} from "./AdminTaskStepFormFields";

export function AdminTaskStepForm(props: AdminTaskStepFormProps) {
  const { taskId, editingStep, stepFormError, stepFormLoading, onSubmitStep, onCancel } = props;
  const formRef = useRef<HTMLFormElement | null>(null);
  const firstFieldRef = useRef<HTMLInputElement | null>(null);

  useEffect(() => {
    formRef.current?.scrollIntoView({ behavior: "smooth", block: "nearest" });
    firstFieldRef.current?.focus({ preventScroll: true });
  }, [editingStep?.id, taskId]);

  return (
    <form
      ref={formRef}
      className="step-form"
      onSubmit={(event) => void onSubmitStep(event, taskId)}
    >
      <StepFormHeader editingStep={editingStep} onCancel={onCancel} />

      <div className="task-form__grid" style={{ gap: "0.5rem" }}>
        <StepNameAndTypeFields props={props} firstFieldRef={firstFieldRef} />
        <StepConnectorFields props={props} />
        <StepInstructionsAndRuntimeFields props={props} />
        <AdminTaskStepTypeFields
          stepFormType={props.stepFormType}
          stepFormAgentId={props.stepFormAgentId}
          setStepFormAgentId={props.setStepFormAgentId}
          panelAgents={props.panelAgents}
          stepFormContextFields={props.stepFormContextFields}
          setStepFormContextFields={props.setStepFormContextFields}
          stepFormConnectorParams={props.stepFormConnectorParams}
          setStepFormConnectorParams={props.setStepFormConnectorParams}
          stepFormMaxFix={props.stepFormMaxFix}
          setStepFormMaxFix={props.setStepFormMaxFix}
          stepFormTimeout={props.stepFormTimeout}
          setStepFormTimeout={props.setStepFormTimeout}
        />
      </div>

      {stepFormError ? (
        <div className="admin-panel__form-error">{stepFormError}</div>
      ) : null}

      <StepFormActions editingStep={editingStep} stepFormLoading={stepFormLoading} onCancel={onCancel} />
    </form>
  );
}
