import { useState } from "react";

import { formatMoney } from "./obFormat";
import { axisTop } from "./usageModel";

type Props = { days: Array<{ day: string; spend: number }> };

const label = (day: string) =>
  new Date(`${day}T00:00:00Z`).toLocaleDateString("en-GB", { day: "numeric", month: "short", timeZone: "UTC" });

// Daily spend (priced usage): one series, one neutral ink, a value on hover or focus, and a table view.
export function SpendTrend({ days }: Props) {
  const [asTable, setAsTable] = useState(false);
  const [tip, setTip] = useState<{ text: string; x: number; y: number } | null>(null);
  const top = axisTop(days.map((item) => item.spend));
  const ticks = [top, top * 0.75, top / 2, top / 4, 0];
  const show = (target: HTMLElement, text: string) => {
    const rect = target.getBoundingClientRect();
    setTip({ text, x: Math.min(rect.left + 12, globalThis.innerWidth - 160), y: rect.top - 34 });
  };

  return (
    <div className="admin-panel__card">
      <div className="admin-panel__section-header">
        <span>Daily spend (priced usage, USD)</span>
        <button type="button" className="ob-link" onClick={() => setAsTable(!asTable)}>
          {asTable ? "Show as chart" : "Show as table"}
        </button>
      </div>
      {asTable ? (
        <table className="admin-panel__table">
          <thead><tr><th>Day</th><th className="ob-num">Spend</th></tr></thead>
          <tbody>
            {days.map((item) => (
              <tr key={item.day}><td>{label(item.day)}</td><td className="ob-num">{formatMoney(item.spend)}</td></tr>
            ))}
          </tbody>
        </table>
      ) : (
        <div className="ob-chart">
          <div className="ob-plot">
            <div className="ob-yaxis" aria-hidden="true">{ticks.map((tick) => <span key={tick}>{formatMoney(tick)}</span>)}</div>
            <div className="ob-bars" role="img" aria-label={`Daily spend over ${days.length} days`}>
              {days.map((item) => {
                const text = `${label(item.day)} · ${formatMoney(item.spend)}`;
                return (
                  <span key={item.day} className="ob-bar" tabIndex={0} aria-label={text}
                    style={{ ["--h" as string]: `${((item.spend / top) * 100).toFixed(1)}%` }}
                    onMouseEnter={(event) => show(event.currentTarget, text)} onMouseLeave={() => setTip(null)}
                    onFocus={(event) => show(event.currentTarget, text)} onBlur={() => setTip(null)} />
                );
              })}
            </div>
          </div>
          {days.length ? (
            <div className="ob-xaxis">
              {[days[0], days[Math.floor(days.length / 2)], days[days.length - 1]].map((item, index) => (
                <span key={`${item.day}-${index}`}>{label(item.day)}</span>
              ))}
            </div>
          ) : null}
        </div>
      )}
      {tip ? <div className="ob-tip" style={{ left: tip.x, top: tip.y }}>{tip.text}</div> : null}
    </div>
  );
}
