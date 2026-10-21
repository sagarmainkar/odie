import { useEffect, useState } from "react";
import { getJSON, postJSON } from "../api";
import { macAppLine, onAMac, type MacApps, type MacAppRow, type MacCalendar } from "../mac";
import { Icon, Tile, type IconName, type TileColor } from "./Tile";

const LOOK: Record<string, [IconName, TileColor]> = { mail: ["mail", "blue"], calendar: ["cal", "orange"], reminders: ["bell", "pink"], contacts: ["chat", "violet"] };

function Dot({ status }: { status: MacAppRow["status"] }) {
  const colour = status === "granted" ? "bg-moss" : status === "denied" ? "bg-ember" : "bg-dim";
  return <span className={`inline-block w-2.5 h-2.5 rounded-full ${colour}`} aria-hidden="true" />;
}

/** The Mac's own apps, one row each: what it is, whether Odie may read it, and the switch that makes macOS ask,
 * right then, on the Mac the page is open on. Off a Mac the rows only show state. Once Calendar is allowed, a picker
 * says which calendar events Odie adds go into. */
export function MacAppsBlock({ data, onChange, mac = onAMac() }: { data: MacApps; onChange: (next: MacApps) => void; mac?: boolean }) {
  const [busy, setBusy] = useState("");
  const [calendars, setCalendars] = useState<MacCalendar[] | null>(null);
  const calendarOk = data.apps.some((a) => a.id === "calendar" && a.status === "granted");
  useEffect(() => {
    if (calendarOk && calendars === null) getJSON<{ calendars: MacCalendar[] }>("/api/mac/calendars").then((r) => setCalendars(r.calendars)).catch(() => setCalendars([]));
  }, [calendarOk, calendars]);
  async function allow(id: string) {
    setBusy(id);
    try { onChange(await postJSON<MacApps>(`/api/mac/apps/${id}/allow`, {})); }
    catch { /* the rows stay as they were */ }
    setBusy("");
  }
  async function choose(name: string) {
    await fetch("/api/mac/calendar", { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ name }) });
    onChange({ ...data, default_calendar: name });
  }
  return (
    <div className="flex flex-col" data-block="mac-apps">
      {data.apps.map((a) => {
        const [icon, color] = LOOK[a.id] ?? ["spark", "ink"];
        return (
          <div key={a.id} className="flex items-center gap-3 px-4 py-3 min-h-14 border-b border-line last:border-b-0">
            <Tile icon={icon} color={color} small />
            <span className="flex-1 min-w-0">
              <b className="block text-[14.5px] font-semibold leading-5">{a.name}</b>
              <span className="flex items-center gap-1.5 text-[12.5px] text-muted"><Dot status={a.status} />{macAppLine(a.status, mac)}</span>
            </span>
            {a.status !== "granted" && mac && (
              <button type="button" onClick={() => void allow(a.id)} disabled={busy !== ""} aria-label={`Allow ${a.name}`}
                className="h-9 px-4 rounded-full bg-ember text-on-ember text-[13.5px] font-semibold disabled:opacity-60">
                {busy === a.id ? "Asking…" : "Allow"}
              </button>
            )}
            {a.status === "granted" && <span className="text-moss-text"><Icon name="check" size={18} stroke={2.6} /></span>}
          </div>
        );
      })}
      {calendarOk && (
        <label className="flex items-center gap-3 px-4 py-3 min-h-14 border-t border-line text-[13.5px]">
          <span className="flex-1 text-muted">Events Odie adds go into</span>
          <select value={data.default_calendar} onChange={(e) => void choose(e.target.value)} aria-label="Calendar for events Odie adds"
            className="h-9 px-3 rounded-full bg-well border border-line text-[13.5px] max-w-[55%]">
            <option value="">First writable calendar</option>
            {(calendars ?? []).filter((c) => c.writable).map((c) => <option key={c.name} value={c.name}>{c.name}</option>)}
          </select>
        </label>
      )}
    </div>
  );
}
