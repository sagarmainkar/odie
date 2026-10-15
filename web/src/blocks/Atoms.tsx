// Atoms and the callout: small pieces a reply can place on their own or inside a row, section or grid.
import { useContext } from "react";
import { Icon, type IconName } from "../components/Tile";
import { SafeImage } from "../components/ImageStrip";
import { ChatActions } from "./ChatActions";
import { InCard } from "./InCard";
import { InlineText } from "./InlineText";
import { badgeClass } from "./inlineSyntax";
import { formatAmount } from "./parse";
import type { Tone } from "./parse/callout";

export function Heading({ text }: { text: string }) {
  return <div className="text-[17px] leading-[23px] font-bold tracking-[-0.01em] mt-3 mb-1"><InlineText text={text} /></div>;
}

export function Text({ text }: { text: string }) {
  return <div className="text-[15px] leading-[22px] text-ink-2 my-1.5"><InlineText text={text} /></div>;
}

export function Badge({ text, tone }: { text: string; tone?: "good" | "warn" }) {
  return <div className="my-1.5"><span className={`chip ${badgeClass(tone)}`}>{text}</span></div>;
}

/** run sends the message (like an actions button); url opens the page. */
export function Button({ label, run, url }: { label: string; run?: string; url?: string }) {
  const { send, busy } = useContext(ChatActions);
  if (run) {
    return (
      <div className="my-2">
        <button type="button" disabled={busy} onClick={() => send(run)} className="pill pill-solid h-10 text-[14px] shadow-none disabled:opacity-40">
          <Icon name="spark" size={15} /> {label}
        </button>
      </div>
    );
  }
  return (
    <div className="my-2">
      <a href={url} target="_blank" rel="noreferrer" className="pill h-10 text-[14px] block-tap"><Icon name="globe" size={15} /> {label}</a>
    </div>
  );
}

export function LinkLine({ text, url }: { text: string; url: string }) {
  return (
    <div className="my-1.5">
      <a href={url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1.5 text-[14px] font-semibold text-ember-text underline underline-offset-2">
        <Icon name="globe" size={14} stroke={2.2} />{text}
      </a>
    </div>
  );
}

export function Picture({ url, caption }: { url: string; caption?: string }) {
  return (
    <figure className="my-2">
      <SafeImage src={url} alt={caption} className="block w-full max-h-[260px] @xl:max-h-[380px] object-cover rounded-[20px] border border-line" />
      {caption && <figcaption className="text-[12px] leading-4 text-muted mt-1.5 px-1">{caption}</figcaption>}
    </figure>
  );
}

/** One progress bar: label on the left, "6 / 9 items" (or "62%") on the right. On its own, or in a row or grid, it sits
 *  in a small card like a stat; inside a section's card it goes without one. */
export function Bar({ label, value, max, unit }: { label: string; value: number; max: number; unit?: string }) {
  const inCard = useContext(InCard);
  const share = Math.max(0, Math.min(1, value / max));
  const frame = inCard ? "my-2" : "glass glass-solid rounded-[20px] px-3.5 py-3 my-2";
  return (
    <div className={frame}>
      <div className="flex items-baseline gap-2 text-[13px]">
        <span className="flex-1 min-w-0 font-semibold text-ink-2">{label}</span>
        <span className="tabular-nums text-muted whitespace-nowrap">{barAmount(value, max, unit)}</span>
      </div>
      <div className="mt-1.5 h-2 rounded-full bg-ember-tint overflow-hidden">
        <div className="h-full rounded-full bg-brand" style={{ width: `${share * 100}%` }} />
      </div>
    </div>
  );
}

/** 62 of 100 with no unit → "62%"; 6 of 9 items → "6 / 9 items"; money → "₹7,200 / ₹8,000". */
function barAmount(value: number, max: number, unit?: string): string {
  if (max === 100 && !unit) return `${value}%`;
  const money = formatAmount(value, unit);
  if (money !== null) return `${money} / ${formatAmount(max, unit)}`;
  const amount = `${value.toLocaleString()} / ${max.toLocaleString()}`;
  if (unit) return `${amount} ${unit}`;
  return amount;
}

export function Divider() {
  return <div className="h-px bg-line my-3" role="separator" />;
}

// How each callout tone looks: its tint, its ink and its icon.
const TONE_LOOK: Record<Tone, { box: string; ink: string; icon: IconName }> = {
  info: { box: "bg-ember-tint", ink: "text-ember-text", icon: "info" },
  tip: { box: "bg-good-tint", ink: "text-good", icon: "spark" },
  warn: { box: "bg-warn-tint", ink: "text-warn-ink", icon: "alert" },
};

/** A tinted box with an icon: a warning, a tip, or the one-line takeaway. */
export function Callout({ tone, title, text }: { tone: Tone; title?: string; text: string }) {
  const look = TONE_LOOK[tone];
  return (
    <div className={`${look.box} rounded-[20px] px-3.5 py-3 my-2 flex gap-2.5`}>
      <span className={`${look.ink} shrink-0 mt-px`}><Icon name={look.icon} size={18} stroke={2.2} /></span>
      <div className="min-w-0 text-[14px] leading-[20px]">
        {title && <div className="font-bold text-ink"><InlineText text={title} /></div>}
        <div className="text-ink-2"><InlineText text={text} /></div>
      </div>
    </div>
  );
}
