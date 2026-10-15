import { useContext } from "react";
import { Icon } from "../components/Tile";
import { PrivateReply } from "../privateReply";
import { ChatActions } from "./ChatActions";
import type { Day, Step, Stop, TileItem } from "./parse";
import { wideColumns } from "./wideColumns";

// Washes for tiles without a photo: the evening sky, tile by tile.
const WASH = [
  "linear-gradient(160deg,#F7A58F 0%,#C77DDE 100%)", "linear-gradient(160deg,#9C8CF2 0%,#5E6FD8 100%)",
  "linear-gradient(160deg,#F6B7A0 0%,#E07FA0 100%)", "linear-gradient(160deg,#FFC98B 0%,#F08A7A 100%)",
  "linear-gradient(160deg,#B7A3F5 0%,#E79BC4 100%)", "linear-gradient(160deg,#8FC6E8 0%,#8C8CF0 100%)",
];

/** Cover cards: a photo (or a wash), a frosted icon chip, a title and one line. A tap asks (fills the composer) or runs. */
export function Tiles({ items }: { items: TileItem[] }) {
  const { send, fill, busy } = useContext(ChatActions);
  const held = useContext(PrivateReply);  // a private chat's tiles go without their web photos
  return (
    <div className={`grid grid-cols-2 ${wideColumns(items.length)} gap-2.5 my-2`}>
      {items.map((t, i) => {
        const act = t.run ? () => send(t.run!) : t.ask ? () => fill(t.ask!) : undefined;
        return (
          <button key={i} type="button" onClick={act} disabled={!act || (!!t.run && busy)}
            className="relative aspect-[1/1.08] rounded-[24px] overflow-hidden text-left text-white active:scale-[.98] transition-transform disabled:active:scale-100"
            style={{ background: t.image && !held ? `center/cover no-repeat url("${t.image}"), ${WASH[i % WASH.length]}` : WASH[i % WASH.length] }}>
            <span className="absolute inset-0" style={{ background: "linear-gradient(180deg,rgba(0,0,0,0) 35%,rgba(20,10,30,.62) 100%)" }} />
            {t.icon && (
              <span className="absolute top-3 left-3 w-10 h-10 rounded-[14px] grid place-items-center bg-white/25 backdrop-blur-md border border-white/35">
                <Icon name={t.icon} size={19} stroke={2.2} />
              </span>
            )}
            <span className="absolute left-3.5 right-3 bottom-3">
              <b className="block text-[16px] leading-5 font-bold tracking-[-0.01em] [text-shadow:0_1px_8px_rgba(0,0,0,.25)]">{t.title}</b>
              {t.subtitle && <span className="block text-[12.5px] leading-4 mt-1 text-white/85 line-clamp-2">{t.subtitle}</span>}
            </span>
          </button>
        );
      })}
    </div>
  );
}

/** A milestone track: checkpoints done ✓, the rest locked, and how far along "value / goal" is. */
export function Progress({ title, value, goal, unit, steps }: { title: string; value: number; goal: number; unit?: string; steps: Step[] }) {
  const u = unit ? ` ${unit}` : "";
  const nodes = steps.length ? steps : [];
  // Nodes sit evenly along the track; the fill reaches between them in proportion to value.
  const pos = (() => {
    if (!nodes.length) return Math.max(0, Math.min(1, value / goal));
    if (value <= nodes[0].at) return 0;
    for (let k = 1; k < nodes.length; k++) {
      if (value < nodes[k].at) return (k - 1 + (value - nodes[k - 1].at) / (nodes[k].at - nodes[k - 1].at)) / (nodes.length - 1);
    }
    return 1;
  })();
  return (
    <div className="rounded-[24px] px-4 py-3.5 my-2 border border-white/60" style={{ background: "color-mix(in srgb, var(--t-good) 14%, var(--t-surface-2))" }}>
      <div className="flex items-center gap-2">
        <span className="text-good"><Icon name="trophy" size={19} stroke={2.2} /></span>
        <b className="text-[17px] font-bold tracking-[-0.01em]">{title}</b>
        <span className="ml-auto flex items-center gap-1 text-[14px] font-semibold tabular-nums text-ink-2">
          <span className="text-good"><Icon name="flame" size={15} stroke={2.2} /></span>{value.toLocaleString()}/{goal.toLocaleString()}{u}
        </span>
      </div>
      {nodes.length === 0 ? (
        <div className="relative mt-4 mb-1 h-2">
          <div className="absolute inset-0 rounded-full bg-good/20" />
          <div className="absolute inset-y-0 left-0 rounded-full bg-good chart-draw" style={{ width: `${pos * 100}%` }} />
        </div>
      ) : (
        <>
          {/* Each checkpoint gets an equal column: the dot sits at its centre and its label wraps inside it, so long
              names ("Day 3 · Chilapada") never run into the next one. */}
          <div className="relative mt-4 h-6">
            <div className="absolute top-1/2 -translate-y-1/2 h-2 rounded-full bg-good/20" style={{ left: `${50 / nodes.length}%`, right: `${50 / nodes.length}%` }} />
            <div className="absolute top-1/2 -translate-y-1/2 h-2 rounded-full bg-good chart-draw"
              style={{ left: `${50 / nodes.length}%`, width: `${((nodes.length - 1) / nodes.length) * 100 * pos}%` }} />
            {nodes.map((n, k) => {
              const done = value >= n.at;
              return (
                <span key={k} className="absolute top-1/2 -translate-y-1/2 -translate-x-1/2" style={{ left: `${((k + 0.5) / nodes.length) * 100}%` }}>
                  <span className={`grid place-items-center w-8 h-6 rounded-full border-2 ${done ? "bg-good border-good text-white" : "bg-surface-2 border-good/30 text-good/70"}`}>
                    <Icon name={done ? "check" : "lock"} size={12} stroke={2.6} />
                  </span>
                </span>
              );
            })}
          </div>
          <div className="grid mt-2" style={{ gridTemplateColumns: `repeat(${nodes.length}, minmax(0, 1fr))` }}>
            {nodes.map((n, k) => (
              <span key={k} className="px-0.5 text-center text-[11.5px] leading-[14px] font-medium text-muted line-clamp-2 [overflow-wrap:anywhere]">{n.label}</span>
            ))}
          </div>
        </>
      )}
    </div>
  );
}

/** A streak: the count, a badge, and the week with each day ticked, today marked. */
export function Streak({ count, label, unit, days }: { count: number; label: string; unit: string; days: Day[] }) {
  const one = count === 1 && unit.endsWith("s") ? unit.slice(0, -1) : unit;
  return (
    <div className="glass glass-solid rounded-[24px] my-2 overflow-hidden">
      <div className="flex items-center px-4 pt-3.5 pb-3">
        <div>
          <div className="text-[12px] font-semibold tracking-[.06em] uppercase text-ember-text">{label}</div>
          <div className="text-[34px] leading-[40px] font-extrabold tracking-[-0.03em] tabular-nums">{count} <span className="capitalize">{one}</span></div>
        </div>
        <span className="ml-auto w-14 h-14 rounded-full grid place-items-center text-white shadow-[0_8px_20px_-8px_rgba(240,150,40,.7)]"
          style={{ background: "radial-gradient(circle at 35% 30%,#FFE08A,#F6A623 55%,#E07B14)" }}>
          <Icon name="star" size={24} stroke={2.4} />
        </span>
      </div>
      {days.length > 0 && (
        <div className="grid border-t border-line px-2 py-3" style={{ gridTemplateColumns: `repeat(${days.length}, minmax(0, 1fr))` }}>
          {days.map((d, k) => (
            <div key={k} className="flex flex-col items-center gap-1.5">
              <span className={`text-[12.5px] ${d.today ? "font-bold text-ink" : "text-muted"}`}>{d.label}</span>
              {d.done ? (
                <span className="w-8 h-8 rounded-full grid place-items-center bg-ember-tint text-ember-text"><Icon name="check" size={15} stroke={2.6} /></span>
              ) : (
                <span className={`w-8 h-8 grid place-items-center text-[17px] tabular-nums ${d.today ? "font-bold text-ink" : "text-dim"}`}>{d.date ?? "·"}</span>
              )}
              <span className={`w-1 h-1 rounded-full ${d.today ? "bg-ink-2" : "bg-transparent"}`} />
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

/** A plan, day by day: times down the side, each stop with its place and a note. */
export function Timeline({ title, groups }: { title?: string; groups: { label: string; items: Stop[] }[] }) {
  return (
    <div className="glass glass-solid rounded-[24px] px-4 py-3.5 my-2 flex flex-col gap-3">
      {title && <b className="text-[17px] font-bold tracking-[-0.01em]">{title}</b>}
      {groups.map((g, gi) => (
        <div key={gi} className="flex flex-col">
          {g.label && <span className="chip chip-soft self-start mb-2">{g.label}</span>}
          {g.items.map((s, k) => (
            <div key={k} className="grid grid-cols-[46px_22px_1fr] gap-x-1.5">
              <span className="text-[12.5px] font-semibold tabular-nums text-muted pt-[3px] text-right">{s.time ?? ""}</span>
              <span className="flex flex-col items-center">
                <span className="w-[22px] h-[22px] rounded-full grid place-items-center bg-ember-tint text-ember-text shrink-0">
                  {s.icon ? <Icon name={s.icon} size={12} stroke={2.4} /> : <span className="w-1.5 h-1.5 rounded-full bg-brand" />}
                </span>
                {k < g.items.length - 1 && <span className="w-px flex-1 bg-line-2 my-1" />}
              </span>
              <div className={`min-w-0 ${k < g.items.length - 1 ? "pb-3" : ""}`}>
                <div className="text-[15px] leading-[21px] font-semibold">{s.title}</div>
                {s.place && <div className="flex items-center gap-1 text-[12.5px] text-muted mt-0.5"><Icon name="pin" size={12} stroke={2.2} />{s.place}</div>}
                {s.note && <div className="text-[13px] leading-[18px] text-ink-2 mt-1">{s.note}</div>}
              </div>
            </div>
          ))}
        </div>
      ))}
    </div>
  );
}
