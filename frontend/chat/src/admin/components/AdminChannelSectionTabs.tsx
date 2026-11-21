import { SegmentedTabs } from "../../layout/SegmentedTabs";
import "./adminChannels.css";

export type AdminChannelSection = "overview" | "alerts" | "voice" | "outbound" | "sessions";

const SECTIONS: Array<{ id: AdminChannelSection; label: string }> = [
  { id: "overview", label: "Overview" },
  // Where a Workspace's run and device problems are sent (email, Slack, Teams).
  { id: "alerts", label: "Problem alerts" },
  // The Call agents settings were unreachable (no nav entry); they live with the channels now.
  { id: "voice", label: "Voice calls" },
  { id: "outbound", label: "Outbound messages" },
  { id: "sessions", label: "Channel sessions" },
];

// The views of the Channels page: the shared SegmentedTabs, small, as the page's second level.
export function AdminChannelSectionTabs({
  value,
  onChange,
}: {
  value: AdminChannelSection;
  onChange: (section: AdminChannelSection) => void;
}) {
  return (
    <SegmentedTabs
      label="Channel sections"
      size="small"
      idPrefix="channel-section"
      testId="channel-sections"
      value={value}
      onChange={(key) => onChange(key as AdminChannelSection)}
      tabs={SECTIONS.map((section) => ({ key: section.id, label: section.label }))}
    />
  );
}
