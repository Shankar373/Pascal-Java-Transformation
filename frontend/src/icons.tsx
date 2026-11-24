import { createElement } from "react";
import type { ReactElement } from "react";

type Attrs = Readonly<Record<string, string | number>>;
type Part = readonly [string, Attrs];

const P = (d: string): Part => ["path", { d }];
const PL = (points: string): Part => ["polyline", { points }];
const L = (x1: number, y1: number, x2: number, y2: number): Part => ["line", { x1, y1, x2, y2 }];
const C = (cx: number, cy: number, r: number): Part => ["circle", { cx, cy, r }];
const R = (x: number, y: number, width: number, height: number, rx?: number): Part =>
  ["rect", rx === undefined ? { x, y, width, height } : { x, y, width, height, rx }];

const DOC = "M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z";
const TRAY = "M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4";

const ICONS: Readonly<Record<string, readonly Part[]>> = {
  logo: [PL("16 18 22 12 16 6"), PL("8 6 2 12 8 18"), L(14, 4, 10, 20)],
  home: [P("M3 9l9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"), PL("9 22 9 12 15 12 15 22")],
  folder: [P("M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z")],
  file: [P(DOC), PL("14 2 14 8 20 8"), L(8, 13, 16, 13), L(8, 17, 16, 17)],
  report: [P(DOC), PL("14 2 14 8 20 8"), PL("9 15 11 17 15 13")],
  gear: [C(12, 12, 3), P("M12 2v3M12 19v3M2 12h3M19 12h3M4.9 4.9l2.1 2.1M17 17l2.1 2.1M4.9 19.1L7 17M17 7l2.1-2.1")],
  upload: [P(TRAY), PL("17 8 12 3 7 8"), L(12, 3, 12, 15)],
  download: [P(TRAY), PL("7 10 12 15 17 10"), L(12, 15, 12, 3)],
  calendar: [R(3, 4, 18, 18, 2), L(16, 2, 16, 6), L(8, 2, 8, 6), L(3, 10, 21, 10)],
  diamond: [["polygon", { points: "12 2 22 12 12 22 2 12", className: "fill-accent" }], ["circle", { cx: 12, cy: 12, r: 2.2, className: "fill-white" }]],
  zip: [P(DOC), PL("14 2 14 8 20 8"), P("M10 12h2M10 15h2M10 18h2")],
  play: [["polygon", { points: "6 3 20 12 6 21 6 3" }]],
  check: [PL("20 6 9 17 4 12")],
  x: [L(18, 6, 6, 18), L(6, 6, 18, 18)],
  warn: [P("M10.3 3.9L1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z"), L(12, 9, 12, 13), L(12, 17, 12.01, 17)],
  copy: [R(9, 9, 13, 13, 2), P("M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1")],
  down: [PL("6 9 12 15 18 9")],
  right: [PL("9 18 15 12 9 6")],
  info: [C(12, 12, 10), L(12, 16, 12, 12), L(12, 8, 12.01, 8)],
  layers: [["polygon", { points: "12 2 2 7 12 12 22 7 12 2" }], PL("2 17 12 22 22 17"), PL("2 12 12 17 22 12")],
  database: [["ellipse", { cx: 12, cy: 5, rx: 9, ry: 3 }], P("M21 12c0 1.66-4 3-9 3s-9-1.34-9-3"), P("M3 5v14c0 1.66 4 3 9 3s9-1.34 9-3V5")],
  puzzle: [P("M10 4a2 2 0 1 1 4 0v2h4a1 1 0 0 1 1 1v4h-2a2 2 0 1 0 0 4h2v4a1 1 0 0 1-1 1h-4v-2a2 2 0 1 0-4 0v2H6a1 1 0 0 1-1-1v-4h2a2 2 0 1 0 0-4H5V7a1 1 0 0 1 1-1h4z")],
  link: [P("M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71"), P("M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71")],
  grid: [R(3, 3, 7, 7), R(14, 3, 7, 7), R(14, 14, 7, 7), R(3, 14, 7, 7)],
  tree: [R(9, 2, 6, 5, 1), R(2, 17, 6, 5, 1), R(16, 17, 6, 5, 1), P("M12 7v4M5 17v-3h14v3")],
  award: [C(12, 8, 7), PL("8.21 13.89 7 23 12 20 17 23 15.79 13.88")],
  monitor: [R(2, 3, 20, 14, 2), L(8, 21, 16, 21), L(12, 17, 12, 21)],
  terminal: [PL("4 17 10 11 4 5"), L(12, 19, 20, 19)],
  book: [P("M2 3h6a4 4 0 0 1 4 4v14a3 3 0 0 0-3-3H2z"), P("M22 3h-6a4 4 0 0 0-4 4v14a3 3 0 0 1 3-3h7z")],
  chart: [L(6, 20, 6, 12), L(12, 20, 12, 5), L(18, 20, 18, 9)],
  help: [C(12, 12, 10), P("M9.09 9a3 3 0 0 1 5.83 1c0 2-3 3-3 3"), L(12, 17, 12.01, 17)],
  bell: [P("M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9"), P("M13.73 21a2 2 0 0 1-3.46 0")],
  dot: [C(12, 12, 4)],
};

interface IconProps {
  name: string;
  className?: string;
}

export function Icon({ name, className }: IconProps): ReactElement {
  const parts = ICONS[name] ?? ICONS["dot"] ?? [];
  return (
    <svg
      viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}
      strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" focusable="false"
      className={className ? `icon ${className}` : "icon"}
    >
      {parts.map(([tag, attrs], i) => createElement(tag, { ...attrs, key: i }))}
    </svg>
  );
}
