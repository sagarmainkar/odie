import type { ComponentType, ReactNode } from "react";
import { locationRow, NOTE_TEXT, type LocationInfo } from "../location";

/** What Settings' Row takes: the view below fills it and leaves the drawing to Settings (its Row stays private). */
export type RowParts = { ok?: boolean; title: string; sub?: ReactNode; meta?: ReactNode; right?: ReactNode; icon?: { icon: "pin"; color: "green" } };

type Props = {
  info: LocationInfo; now: Date; busy: boolean; Row: ComponentType<RowParts>;
  onTurnOn: () => void; onOff: () => void; onForget: () => void;
};

/** Settings' Location row: the place on the sub line, seen and home on the meta line, Turn on/Off and Forget on the
 * right, and the one-line note drawn UNDER the row across its full width (the row's text column is about 188px wide
 * on a phone, where the note would wrap to four lines). */
export function LocationRowView({ info, now, busy, Row, onTurnOn, onOff, onForget }: Props) {
  const row = locationRow(info, now);
  const link = "h-10 px-2 -mx-2 text-ember-text font-medium disabled:opacity-50";
  const right = (
    <span className="flex items-center gap-3 shrink-0">
      {info.on === true
        ? <button disabled={busy} onClick={onOff} className={link}>Off</button>
        : <button disabled={busy} onClick={onTurnOn} className={link}>Turn on</button>}
      {(info.place || info.home) && <button disabled={busy} onClick={onForget} className={link}>Forget</button>}
    </span>
  );
  return (
    <>
      <Row icon={{ icon: "pin", color: "green" }} ok={row.state === "ok"} title="Location" sub={row.sub} meta={row.meta || undefined} right={right} />
      <div className="location-note px-4 pb-3 -mt-1 text-[12px] leading-4 text-dim border-b border-line last:border-b-0">{NOTE_TEXT}</div>
    </>
  );
}
