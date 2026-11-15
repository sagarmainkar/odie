import { useEffect, useState } from "react";
import { getJSON } from "../api";
import { activityLine, whenWords, type Activity } from "../bots";
import { userLocale } from "../locale";

/** Recent work (a bot's details): its last jobs, its own and those it did for the chief, each opening the
 * conversation it answered in. The record behind it keeps every step (Today's Jobs, More). */
export function BotActivity({ bot }: { bot: string }) {
  const [list, setList] = useState<Activity[] | null>(null);
  useEffect(() => { getJSON<{ activity: Activity[] }>(`/api/bots/${bot}/activity`).then((r) => setList(r.activity)).catch(() => setList([])); }, [bot]);
  const locale = userLocale();
  if (!list || list.length === 0) return null;
  return (
    <div className="px-5 flex flex-col gap-1.5">
      <span className="text-[12.5px] text-muted">Recent work</span>
      <div className="rounded-[16px] bg-well overflow-hidden">
        {list.slice(0, 8).map((a) => {
          const row = (
            <>
              <div className="flex items-center gap-2">
                <span className="text-[13.5px] font-medium truncate">{a.title}</span>
                <span className="ml-auto text-[11.5px] text-muted shrink-0">{whenWords(a.ended_at ?? a.started_at, undefined, locale)}</span>
              </div>
              <div className={`text-[12px] ${a.status === "failed" ? "text-ember-text" : "text-muted"}`}>{activityLine(a)}{a.status === "failed" && a.error ? ` · ${a.error}` : ""}</div>
            </>
          );
          return a.conv
            ? <a key={a.id} href={`#bot/${a.conv_bot ?? bot}/${a.conv}`} className="block px-3 py-2 border-b border-line last:border-b-0">{row}</a>
            : <div key={a.id} className="px-3 py-2 border-b border-line last:border-b-0">{row}</div>;
        })}
      </div>
    </div>
  );
}
