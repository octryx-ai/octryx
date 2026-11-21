export function TraceValue({ value }: { value: unknown }) {
  if (value == null) {
    return (
      <pre className="trace-panel__pre trace-panel__pre--result">null</pre>
    );
  }
  if (typeof value === "string") {
    return (
      <pre className="trace-panel__pre trace-panel__pre--result">{value}</pre>
    );
  }
  return (
    <pre className="trace-panel__pre trace-panel__pre--result">
      {JSON.stringify(value, null, 2)}
    </pre>
  );
}
