import { useState } from "react";
import { castLine, castLineLook, castMarks, clock, playerWords, speakingAt, textToneAt, toneAt, turnAt, type Media } from "../media";
import { PlayPause, usePlayer } from "./VoiceMemo";
import { ShareFile } from "./ShareButton";


/** A podcast: a wider card, unlike the memo pill. The two hosts (the one speaking lit), the title, a scrubber, play
 * with ±15 s, and the transcript by host (a tap on a line jumps there). An audio story is the same card for its cast:
 * "Audio story", "Play story", a tone for each speaker (eight, then cycling) and the cast's voices under the title. */
export function Podcast({ m }: { m: Media }) {
  const p = usePlayer(m);
  const [open, setOpen] = useState(false);
  const hosts = m.hosts ?? [];
  const turns = Array.isArray(m.transcript) ? m.transcript : [];
  const live = p.playing || p.time > 0;
  const who = live ? speakingAt(m, p.time) : -1;
  const turn = live ? turnAt(m, p.time) : -1;
  const pct = p.duration ? Math.min(100, (p.time / p.duration) * 100) : 0;
  const words = playerWords(m);
  const tone = (name: string) => textToneAt(m, Math.max(0, hosts.findIndex((h) => h.name === name)));
  const marks = castMarks(m, hosts.map((h) => h.name));
  return (
    <div className="glass rounded-[26px] p-4 w-full max-w-[420px] flex flex-col gap-3" data-media={m.kind} data-ready={p.ready ? "1" : "0"}>
      <div className="flex items-center gap-3">
        <div className="flex -space-x-2 shrink-0">
          {hosts.map((h, i) => (
            <span key={h.name} title={h.name} aria-label={`${h.name}${who === i ? ", speaking" : ""}`}
              className="w-11 h-11 rounded-full grid place-items-center text-[16px] font-bold text-white transition-transform duration-200"
              style={{ background: toneAt(m, i), zIndex: who === i ? 2 : 1, transform: who === i ? "scale(1.08)" : "none",
                boxShadow: who === i ? `0 0 0 3px var(--t-surface), 0 0 0 5px ${toneAt(m, i)}` : "0 0 0 2px var(--t-surface)" }}>
              {marks[i]}
            </span>
          ))}
        </div>
        <div className="flex-1 min-w-0">
          <div className="text-[11px] uppercase tracking-[0.08em] font-bold text-muted">{words.label}</div>
          <div className="text-[15.5px] font-semibold leading-5 truncate">{m.title}</div>
          <div className={`text-[12.5px] text-muted ${castLineLook(m)}`}>{who >= 0 ? `${hosts[who].name} is speaking` : castLine(m)}</div>
        </div>
        <ShareFile file={m} />
      </div>
      <div>
        <div onClick={p.seekAt} role="slider" aria-label={words.position} aria-valuemin={0} aria-valuemax={Math.round(p.duration)} aria-valuenow={Math.round(p.time)}
          className="h-2 rounded-full bg-well cursor-pointer relative overflow-hidden">
          <div className="absolute inset-y-0 left-0 rounded-full bg-ember" style={{ width: `${pct}%` }} />
        </div>
        <div className="flex justify-between text-[12px] text-muted tabular-nums mt-1"><span>{clock(p.time)}</span><span>{clock(p.duration)}</span></div>
      </div>
      <div className="flex items-center justify-center gap-7">
        <button onClick={() => p.seek(p.time - 15)} aria-label="Back 15 seconds" className="w-11 h-11 rounded-full grid place-items-center text-[13px] font-bold text-ink-2 active:bg-well">−15</button>
        <button onClick={p.toggle} aria-label={p.playing ? words.pause : words.play} className="w-14 h-14 rounded-full bg-ember text-on-ember grid place-items-center">
          <PlayPause playing={p.playing} size={24} />
        </button>
        <button onClick={() => p.seek(p.time + 15)} aria-label="Forward 15 seconds" className="w-11 h-11 rounded-full grid place-items-center text-[13px] font-bold text-ink-2 active:bg-well">+15</button>
      </div>
      {turns.length > 0 && (
        <>
          <button onClick={() => setOpen(!open)} className="self-start text-[12.5px] text-muted font-semibold">{open ? "Hide transcript" : "Transcript"}</button>
          {open && (
            <div className="flex flex-col gap-1 max-h-[300px] overflow-y-auto no-scrollbar -mx-1">
              {turns.map((t, i) => (
                <button key={i} onClick={() => p.seek(t.start)} className={`text-left text-[13.5px] leading-[20px] rounded-[12px] px-2 py-1 ${i === turn ? "bg-well" : ""}`}>
                  <b style={{ color: tone(t.host) }}>{t.host}</b> <span className="text-ink-2">{t.text}</span>
                </button>
              ))}
            </div>
          )}
        </>
      )}
    </div>
  );
}
