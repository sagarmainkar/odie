import { useCallback, useEffect, useState } from "react";
import { getJSON, postJSON } from "../api";
import { ago, askAbout, type NewsBatch } from "../news";
import { SafeImage } from "./ImageStrip";
import { Icon } from "./Tile";
import { usePersona } from "../persona";

const DOT = ["#3b66ff", "#ff7430", "#20b679", "#8455ff", "#ff5490", "#ffaa1c"];

/** Today's news: fetched by Odie every few hours (no model involved). Tap a card to read it; "Ask" hands it to Chat. */
export function NewsSection() {
  const { name } = usePersona();
  const [batch, setBatch] = useState<NewsBatch | null>(null);
  const [topic, setTopic] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const load = useCallback(() => { getJSON<NewsBatch>("/api/news").then(setBatch).catch(() => {}); }, []);
  useEffect(load, [load]);
  async function refresh() {
    setBusy(true);
    try { setBatch(await postJSON<NewsBatch>("/api/news/refresh", {})); } catch { /* keep what we have */ } finally { setBusy(false); }
  }
  if (!batch) return null;
  const topics = batch.topics.filter((t) => batch.items.some((i) => i.topic === t));
  const current = topic && topics.includes(topic) ? topic : topics[0] ?? null;
  const items = batch.items.filter((i) => i.topic === current);
  const sources = [...new Set(batch.items.map((i) => i.source))];
  return (
    <section className="flex flex-col gap-3 rise">
      <div className="flex items-center justify-between px-1">
        <div>
          <div className="text-[21px] font-bold tracking-[-0.015em]">News</div>
          <div className="text-[12.5px] text-muted">{batch.fetched_at ? `Updated ${ago(batch.fetched_at)}` : "Not fetched yet"}</div>
        </div>
        <button onClick={refresh} disabled={busy} aria-label="Refresh news" className="pill w-11 px-0">
          <span className={`flex ${busy ? "animate-spin" : ""}`}><Icon name="refresh" size={17} /></span>
        </button>
      </div>
      {topics.length > 0 && (
        <div className="flex gap-2 overflow-x-auto no-scrollbar -mx-[18px] px-[18px]">
          {topics.map((t) => (
            <button key={t} onClick={() => setTopic(t)}
              className={`chip h-9 px-4 text-[13.5px] ${t === current ? "bg-solid text-on-solid" : "chip-soft"}`}>{t}</button>
          ))}
        </div>
      )}
      {batch.items.length === 0 ? (
        <div className="glass rounded-[22px] px-4 py-3.5 text-[14px] text-muted">News arrives every few hours. Tap refresh to fetch it now.</div>
      ) : items.length === 0 ? (
        <div className="glass rounded-[22px] px-4 py-3.5 text-[14px] text-muted">Nothing new here right now.</div>
      ) : (
        // A phone's cards run to the screen's edges; in a desktop's column they stay inside it, two at a time.
        <div className="flex gap-3 overflow-x-auto no-scrollbar -mx-[18px] px-[18px] lg:mx-0 lg:px-0 pb-2 snap-x snap-mandatory scroll-px-[18px] lg:scroll-px-0">
          {items.map((it) => (
            <article key={it.link} className="glass glass-solid shrink-0 w-[78%] lg:w-[calc(50%-6px)] snap-start rounded-[26px] p-2 pb-3 flex flex-col">
              <a href={it.link} target="_blank" rel="noreferrer" className="flex flex-col flex-1">
                {it.image && <SafeImage src={it.image} className="h-[150px] w-full object-cover rounded-[20px] bg-well" />}
                <div className="flex items-center gap-1.5 mx-2 mt-3 mb-1.5 text-[12px] font-bold text-muted min-w-0">
                  <i className="w-[18px] h-[18px] shrink-0 rounded-full grid place-items-center not-italic text-[10px] text-white" style={{ background: DOT[sources.indexOf(it.source) % DOT.length] }}>{it.source.charAt(0)}</i>
                  <span className="truncate">{it.source}</span>
                  {it.published && <span className="shrink-0 font-medium">· {ago(it.published)}</span>}
                </div>
                <div className="mx-2 text-[15.5px] leading-[1.35] font-bold line-clamp-3 [overflow-wrap:anywhere]">{it.title}</div>
              </a>
              <button onClick={() => { location.hash = `chat?q=${encodeURIComponent(askAbout(it))}`; }} className="pill pill-flat h-9 text-[13px] self-start mx-2 mt-3">
                <Icon name="spark" size={14} /> Ask {name}
              </button>
            </article>
          ))}
        </div>
      )}
    </section>
  );
}
