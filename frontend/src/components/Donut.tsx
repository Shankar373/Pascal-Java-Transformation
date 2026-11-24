import type { ReactElement } from "react";
import { fmt } from "../format";
import type { DistributionGroup } from "../types";
import { Panel } from "./Panel";

interface DonutProps {
  distribution: { total?: number; groups?: DistributionGroup[] } | undefined;
}

const RADIUS = 62;
const CIRCUMFERENCE = 2 * Math.PI * RADIUS;
const CENTER = 80;
const STROKE = 24;
const COLOR_SLOTS = 5;

interface Segment {
  index: number;
  length: number;
  offset: number;
}

function segments(groups: DistributionGroup[], total: number): Segment[] {
  const out: Segment[] = [];
  let offset = 0;
  groups.forEach((g, index) => {
    const length = total > 0 ? (g.count / total) * CIRCUMFERENCE : 0;
    if (length <= 0) return;
    out.push({ index, length, offset });
    offset += length;
  });
  return out;
}

export function Donut({ distribution }: DonutProps): ReactElement {
  const groups = distribution?.groups ?? [];
  const total = distribution?.total ?? 0;
  const gap = groups.length > 1 ? 1.2 : 0;
  return (
    <Panel title="File Distribution" icon="chart" cls="area-dist">
      <div className="donut-wrap">
        <svg viewBox="0 0 160 160" className="donut" role="img" aria-label={`File distribution of ${fmt(total)} files`}>
          <g transform="rotate(-90 80 80)">
            <circle cx={CENTER} cy={CENTER} r={RADIUS} className="donut-track" fill="none" strokeWidth={STROKE} />
            {segments(groups, total).map((s) => (
              <circle
                key={s.index} cx={CENTER} cy={CENTER} r={RADIUS} fill="none" strokeWidth={STROKE}
                className={`donut-seg seg-${s.index % COLOR_SLOTS}`}
                strokeDasharray={`${Math.max(0, s.length - gap).toFixed(3)} ${CIRCUMFERENCE.toFixed(3)}`}
                strokeDashoffset={(-s.offset).toFixed(3)}
              />
            ))}
          </g>
          <text x={80} y={80} textAnchor="middle" className="donut-total">{fmt(total)}</text>
          <text x={80} y={98} textAnchor="middle" className="donut-caption">Files</text>
        </svg>
        <ul className="legend">
          {groups.map((g, i) => (
            <li key={i}>
              <span className={`dot seg-bg-${i % COLOR_SLOTS}`} aria-hidden="true" />
              <span className="legend-label">{g.label}</span>
              <span className="legend-pct">{typeof g.percent === "number" ? `${g.percent.toFixed(1)}%` : "—"}</span>
            </li>
          ))}
        </ul>
      </div>
    </Panel>
  );
}
