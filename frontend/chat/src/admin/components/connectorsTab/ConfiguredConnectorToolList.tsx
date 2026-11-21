import { AdvancedSection } from "../../../layout/FormSection";

type ConnectorTool = { name: string; description: string };

// The tools a connector adds, collapsed so the connection fields come first; a collapsed design-system
// section.
export function ConfiguredConnectorToolList({ tools }: { tools: ConnectorTool[] }) {
  if (tools.length === 0) return null;
  return (
    <AdvancedSection label={`Tools (${tools.length})`} testId="connector-tools">
      <div className="connector-card__tools-list">
        {tools.map((tool) => (
          <div key={tool.name} className="connector-tool">
            <span className="connector-tool__name">{tool.name}</span>
            <span className="connector-tool__desc">{tool.description}</span>
          </div>
        ))}
      </div>
    </AdvancedSection>
  );
}
