import { useEffect, useRef, useState } from "react";
import { clock, filled, mediaUrl, type Media } from "../media";
import { markPlaying, markStopped } from "../playing";

/** Plays one media file. Only one plays at a time: starting one pauses the others. */
export function usePlayer(m: Media) {
  const ref = useRef<HTMLAudioElement | null>(null);
  const [playing, setPlaying] = useState(false);
  const [time, setTime] = useState(0);
  const [duration, setDuration] = useState(m.duration ?? 0);
  const [ready, setReady] = useState(false);
  useEffect(() => {
    const a = new Audio(mediaUrl(m));
    a.preload = "metadata";
    ref.current = a;
    const tick = () => setTime(a.currentTime);
    const meta = () => { setReady(true); if (Number.isFinite(a.duration) && a.duration > 0) setDuration(a.duration); };
    const end = () => { setPlaying(false); setTime(0); markStopped(m.id); };
    const play = () => { setPlaying(true); markPlaying(m.id); };
    const pause = () => { setPlaying(false); markStopped(m.id); };
    const others = (e: Event) => { if ((e as CustomEvent<string>).detail !== m.id) a.pause(); };
    a.addEventListener("timeupdate", tick);
    a.addEventListener("loadedmetadata", meta);
    a.addEventListener("ended", end);
    a.addEventListener("play", play);
    a.addEventListener("pause", pause);
    window.addEventListener("odie:play", others);
    return () => {
      markStopped(m.id);  // the pause below fires after its listener is gone
      a.pause();
      a.removeEventListener("timeupdate", tick);
      a.removeEventListener("loadedmetadata", meta);
      a.removeEventListener("ended", end);
      a.removeEventListener("play", play);
      a.removeEventListener("pause", pause);
      window.removeEventListener("odie:play", others);
      a.removeAttribute("src");
      a.load();
    };
  }, [m.id]);  // eslint-disable-line react-hooks/exhaustive-deps
  function toggle() {
    const a = ref.current;
    if (!a) return;
    if (a.paused) { window.dispatchEvent(new CustomEvent("odie:play", { detail: m.id })); void a.play().catch(() => {}); }
    else a.pause();
  }
  function seek(t: number) {
    const a = ref.current;
    if (!a) return;
    a.currentTime = Math.max(0, Math.min(t, duration || a.duration || 0));
    setTime(a.currentTime);
  }
  const seekAt = (e: React.MouseEvent<HTMLElement>) => {
    const r = e.currentTarget.getBoundingClientRect();
    seek(((e.clientX - r.left) / r.width) * duration);
  };
  return { playing, time, duration, ready, toggle, seek, seekAt };
}

export function PlayPause({ playing, size = 18 }: { playing: boolean; size?: number }) {
  return playing ? (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="currentColor" aria-hidden><rect x="6" y="5" width="4" height="14" rx="1.2" /><rect x="14" y="5" width="4" height="14" rx="1.2" /></svg>
  ) : (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="currentColor" aria-hidden><path d="M8 5.5v13a1 1 0 0 0 1.5.86l10.4-6.5a1 1 0 0 0 0-1.72L9.5 4.64A1 1 0 0 0 8 5.5z" /></svg>
  );
}

/** A voice memo: a compact pill with play/pause, the waveform (played part filled) and the time. */
export function VoiceMemo({ m, autoPlay = false }: { m: Media; autoPlay?: boolean }) {
  const p = usePlayer(m);
  const [open, setOpen] = useState(false);
  useEffect(() => {  // a spoken reminder that just arrived plays (the browser may still say no: then it waits for a tap)
    if (autoPlay) p.toggle();
  }, [autoPlay]);  // eslint-disable-line react-hooks/exhaustive-deps
  const bars = m.peaks?.length ? m.peaks : Array<number>(32).fill(0.4);
  const on = filled(bars, p.duration ? p.time / p.duration : 0);
  return (
    <div className="flex flex-col gap-1.5 w-full max-w-[340px]" data-media={m.kind} data-ready={p.ready ? "1" : "0"}>
      <div className="glass rounded-full flex items-center gap-3 pl-1.5 pr-4 py-1.5">
        <button onClick={p.toggle} aria-label={p.playing ? "Pause voice memo" : "Play voice memo"}
          className="w-10 h-10 rounded-full bg-ember text-on-ember grid place-items-center shrink-0"><PlayPause playing={p.playing} /></button>
        <div onClick={p.seekAt} role="slider" aria-label="Voice memo position" aria-valuemin={0} aria-valuemax={Math.round(p.duration)} aria-valuenow={Math.round(p.time)}
          className="flex-1 min-w-0 flex items-center gap-[2px] h-8 cursor-pointer">
          {bars.map((v, i) => <span key={i} className={`flex-1 rounded-full ${on[i] ? "bg-ember" : "bg-dim/40"}`} style={{ height: `${Math.max(14, v * 100)}%` }} />)}
        </div>
        <span className="text-[12.5px] text-muted tabular-nums shrink-0">{clock(p.playing || p.time ? p.time : p.duration)}</span>
      </div>
      {typeof m.transcript === "string" && m.transcript && (
        <>
          <button onClick={() => setOpen(!open)} className="self-start ml-3 text-[12.5px] text-muted font-semibold">{open ? "Hide transcript" : "Transcript"}</button>
          {open && <div className="ml-3 text-[13.5px] leading-[20px] text-ink-2">{m.transcript}</div>}
        </>
      )}
    </div>
  );
}
