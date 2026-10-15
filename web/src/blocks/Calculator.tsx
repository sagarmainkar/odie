import { useContext, type CSSProperties } from "react";
import { evaluate } from "./formula";
import { FenceValues, formatWithUnit } from "./fenceValues";
import { InCard } from "./InCard";
import { InlineText } from "./InlineText";
import type { CalcInput, CalcOutput } from "./parse";

/** What-if numbers: a slider per input, and results worked out again on every move. The inputs' values are the
 *  fence's shared values, so text elsewhere in the same fence can show them too. Nothing is saved. */
export function Calculator({ title, inputs, outputs }: { title?: string; inputs: CalcInput[]; outputs: CalcOutput[] }) {
  const inCard = useContext(InCard);
  const { values, set } = useContext(FenceValues);
  const frame = inCard ? "my-2" : "glass glass-solid rounded-[20px] px-4 py-3.5 my-2";
  const outputColumns = outputs.length === 1 ? "grid-cols-1" : "grid-cols-2";

  return (
    <div className={frame}>
      {title && <div className="text-[15px] leading-[21px] font-bold mb-1"><InlineText text={title} /></div>}
      {inputs.map((input) => (
        <Slider key={input.id} input={input} value={values.get(input.id) ?? input.value} onMove={(v) => set(input.id, v)} />
      ))}
      {outputs.length > 0 && (
        <div className={`grid ${outputColumns} gap-2 mt-2.5`}>
          {outputs.map((output, i) => <Result key={i} output={output} values={values} />)}
        </div>
      )}
    </div>
  );
}

function Slider({ input, value, onMove }: { input: CalcInput; value: number; onMove: (v: number) => void }) {
  const share = (value - input.min) / (input.max - input.min);
  const fill = { "--fill": `${Math.round(share * 1000) / 10}%` } as CSSProperties;
  return (
    <label className="block py-2">
      <span className="flex items-baseline gap-2">
        <span className="flex-1 min-w-0 text-[13.5px] font-semibold text-ink-2"><InlineText text={input.label} /></span>
        <span className="text-[15px] font-bold tabular-nums whitespace-nowrap">{formatWithUnit(value, input.unit)}</span>
      </span>
      <input type="range" className="slider mt-2" style={fill} min={input.min} max={input.max} step={input.step} value={value}
        onChange={(e) => onMove(Number(e.target.value))} />
      <span className="flex justify-between text-[11px] text-dim tabular-nums mt-0.5">
        <span>{formatWithUnit(input.min, input.unit)}</span>
        <span>{formatWithUnit(input.max, input.unit)}</span>
      </span>
    </label>
  );
}

/** One result: its label and its value now, or "–" when the formula can't be worked out (that result only). */
function Result({ output, values }: { output: CalcOutput; values: ReadonlyMap<string, number> }) {
  const value = evaluate(output.formula, values);
  let shown = "–";
  if (value !== null) shown = formatWithUnit(value, output.unit);
  return (
    <div className="rounded-[16px] bg-ember-tint px-3.5 py-2.5 min-w-0">
      <div className="text-[12px] font-semibold text-muted"><InlineText text={output.label} /></div>
      <div className="text-[20px] leading-tight font-extrabold tracking-[-0.02em] tabular-nums mt-0.5 [overflow-wrap:anywhere]" aria-live="polite">{shown}</div>
    </div>
  );
}
