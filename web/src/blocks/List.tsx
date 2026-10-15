import { useContext } from "react";
import { Icon } from "../components/Tile";
import { PrivateReply } from "../privateReply";
import { ChatActions } from "./ChatActions";
import { InCard } from "./InCard";
import { InlineText } from "./InlineText";
import type { ListItem } from "./parse";
import { avatarColour, initialOf, rowLead } from "./rowAvatar";

/** Rich rows: a rank number or an icon or photo (or, with neither, the title's first letter in a coloured circle), a
 *  title and a line under it, a value on the right. A row with run sends a message when tapped; a row with url opens
 *  the page. */
export function List({ title, ranked, items }: { title?: string; ranked: boolean; items: ListItem[] }) {
  const inCard = useContext(InCard);
  const frame = inCard ? "my-2" : "glass glass-solid rounded-[20px] my-2 overflow-hidden";
  return (
    <div className={frame}>
      {title && <div className={`${inCard ? "" : "px-4"} pt-3 pb-1 text-[13px] font-bold text-muted`}><InlineText text={title} /></div>}
      {items.map((item, i) => <ListRow key={i} item={item} rank={ranked ? i + 1 : null} flush={inCard} />)}
    </div>
  );
}

function ListRow({ item, rank, flush }: { item: ListItem; rank: number | null; flush: boolean }) {
  const { send, busy } = useContext(ChatActions);
  const held = useContext(PrivateReply);  // a private chat's rows go without their web photos
  const lead = rowLead(item, rank !== null, held);
  const padding = flush ? "py-3" : "px-4 py-3";
  const rowClass = `w-full flex items-center gap-3 ${padding} text-left border-t border-line first:border-t-0`;

  const body = (
    <>
      {rank !== null && (
        <span className="w-7 h-7 shrink-0 rounded-full grid place-items-center bg-ember-tint text-ember-text text-[13px] font-bold tabular-nums">{rank}</span>
      )}
      {lead === "image" && <img src={item.image} alt="" loading="lazy" referrerPolicy="no-referrer" className="w-11 h-11 shrink-0 rounded-[12px] object-cover bg-well" />}
      {lead === "icon" && item.icon && (
        <span className="w-9 h-9 shrink-0 rounded-[12px] grid place-items-center bg-ember-tint text-ember-text"><Icon name={item.icon} size={17} stroke={2.2} /></span>
      )}
      {lead === "initial" && (
        <span className="w-9 h-9 shrink-0 rounded-full grid place-items-center text-white text-[15px] font-bold" style={{ background: avatarColour(item.title) }} aria-hidden="true">
          {initialOf(item.title)}
        </span>
      )}
      <span className="flex-1 min-w-0">
        <span className="block text-[15px] leading-[20px] font-semibold"><InlineText text={item.title} /></span>
        {item.subtitle && <span className="block text-[13px] leading-[18px] text-muted mt-0.5 line-clamp-2"><InlineText text={item.subtitle} /></span>}
      </span>
      {item.value && <span className="shrink-0 text-[14px] font-bold tabular-nums whitespace-nowrap"><InlineText text={item.value} /></span>}
      {(item.run || item.url) && <Chevron />}
    </>
  );

  if (item.run) {
    const run = item.run;
    return <button type="button" disabled={busy} onClick={() => send(run)} className={`${rowClass} active:bg-well`}>{body}</button>;
  }
  if (item.url) {
    return <a href={item.url} target="_blank" rel="noreferrer" className={`${rowClass} block-tap active:bg-well`}>{body}</a>;
  }
  return <div className={rowClass}>{body}</div>;
}

function Chevron() {
  return (
    <svg className="shrink-0 text-dim" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M9 6l6 6-6 6" />
    </svg>
  );
}
