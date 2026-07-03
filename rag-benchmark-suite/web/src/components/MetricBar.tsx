export default function MetricBar({
  value,
  threshold,
  higherIsBetter = true,
  format = (v: number) => v.toFixed(2),
}: {
  value: number | null | undefined;
  threshold: number;
  higherIsBetter?: boolean;
  format?: (v: number) => string;
}) {
  if (value === null || value === undefined) {
    return <span style={{ color: "#aab1b8" }}>—</span>;
  }
  const passed = higherIsBetter ? value >= threshold : value <= threshold;
  const pct = Math.max(0, Math.min(1, higherIsBetter ? value : 1 - value)) * 100;
  return (
    <div className="metric-cell">
      <span>{format(value)}</span>
      <div className="metric-bar-track">
        <div
          className={`metric-bar-fill ${passed ? "" : "bad"}`}
          style={{ width: `${pct}%` }}
        />
      </div>
    </div>
  );
}
