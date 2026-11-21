type ResumeNoticeProps = {
  resumeState?: string | null;
};

function getResumeCopy(resumeState?: string | null) {
  const normalized = String(resumeState || "")
    .trim()
    .toLowerCase();
  if (normalized === "approval_approved") {
    return {
      eyebrow: "Resume after approval",
      title: "Continuing the current thread",
      body: "The approved step is being continued from the existing turn context. New output belongs to the same thread, not a fresh run.",
    };
  }
  if (normalized === "approval_rejected") {
    return {
      eyebrow: "Resume after rejection",
      title: "Continuing with a safer path",
      body: "The rejected action will not be retried. The agent is continuing from the same thread and should switch to the safest next step or a read-only alternative.",
    };
  }
  return null;
}

export function ResumeNotice({ resumeState }: ResumeNoticeProps) {
  const copy = getResumeCopy(resumeState);
  if (!copy) {
    return null;
  }

  return (
    <aside className="resume-notice" aria-live="polite">
      <div className="resume-notice__eyebrow">{copy.eyebrow}</div>
      <div className="resume-notice__title">{copy.title}</div>
      <div className="resume-notice__body">{copy.body}</div>
    </aside>
  );
}
