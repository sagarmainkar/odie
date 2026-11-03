// A stacked area chart's marks: each part filled between its band's bottom and top, its top edge drawn as a line.
import { partColour, type Band } from "./chartData";
import { linePath } from "./chartGeometry";
import type { XYLayout } from "./chartLayout";

export function AreaMarks({ bands, layout }: { bands: (Band | null)[][]; layout: XYLayout }) {
  return (
    <g>
      <line x1={layout.left} x2={layout.right} y1={layout.base} y2={layout.base} className="chart-rule" />
      {bands.map((partBands, k) => <Area key={k} bands={partBands} layout={layout} colour={partColour(k)} />)}
    </g>
  );
}

function Area({ bands, layout, colour }: { bands: (Band | null)[]; layout: XYLayout; colour: string }) {
  const top: [number, number][] = [];
  const bottom: [number, number][] = [];
  bands.forEach((b, i) => {
    if (b === null) return;
    top.push([layout.xAt(i), layout.yAt(b.to)]);
    bottom.push([layout.xAt(i), layout.yAt(b.from)]);
  });
  if (!top.length) return null;
  const topEdge = linePath(top);
  const backAlongBottom = linePath(bottom.reverse()).replace(/^M/, "L");
  return (
    <g>
      <path d={`${topEdge} ${backAlongBottom} Z`} fill={colour} fillOpacity=".3" />
      <path d={topEdge} fill="none" stroke={colour} strokeWidth="2" strokeLinejoin="round" strokeLinecap="round" />
    </g>
  );
}
