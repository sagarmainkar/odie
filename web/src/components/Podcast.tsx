import { useState } from "react";
import {
  SPEAKER_SCALE, castLine, castRole, clock, hostInitial, isStory, linesAt, nameLineAt, playerWords, showsWhoIsWho,
  speakingAt, textToneAt, toneAt, turnAt, type Host, type Media,
} from "../media";
import { Face } from "./Face";
import { PlayPause, usePlayer } from "./VoiceMemo";
import { ShareFile } from "./ShareButton";

type Player = ReturnType<typeof usePlayer>;

/** A podcast or an audio story: a wider card, unlike the memo pill. A podcast shows its two hosts (the one speaking
 * lit) beside the title; a story (a user skill can make one) shows a teaser, who's who with a drawn face each, and
 * while it plays the faces with the speaker's grown and the line being said. Both have a scrubber, play with ±15 s,
 * and the transcript by speaker (a tap on a line jumps there). */
export function Podcast({ m }: { m: Media }) {
  if (isStory(m)) return <StoryCard m={m} />;
  return <PodcastCard m={m} />;
}

/** A podcast: the two hosts' coloured letters beside the title, the one speaking lit. */
function PodcastCard({ m }: { m: Media }) {
  const p = usePlayer(m);
  const [open, setOpen] = useState(false);
  const hosts = m.hosts ?? [];
  const live = p.playing || p.time > 0;
  const who = live ? speakingAt(m, p.time) : -1;
  const words = playerWords(m);
  return (
    <div className="glass rounded-[26px] p-4 w-full max-w-[420px] flex flex-col gap-3" data-media={m.kind} data-ready={p.ready ? "1" : "0"}>
      <div className="flex items-center gap-3">
        <div className="flex -space-x-2 shrink-0">
          {hosts.map((h, i) => (
            <span key={h.name} title={h.name} aria-label={`${h.name}${who === i ? ", speaking" : ""}`}
              className="w-11 h-11 rounded-full grid place-items-center text-[16px] font-bold text-white transition-transform duration-200"
              style={{ background: toneAt(m, i), zIndex: who === i ? 2 : 1, transform: who === i ? "scale(1.08)" : "none",
                boxShadow: who === i ? `0 0 0 3px var(--t-surface), 0 0 0 5px ${toneAt(m, i)}` : "0 0 0 2px var(--t-surface)" }}>
              {hostInitial(h.name)}
            </span>
          ))}
        </div>
        <div className="flex-1 min-w-0">
          <div className="text-[11px] uppercase tracking-[0.08em] font-bold text-muted">{words.label}</div>
          <div className="text-[15.5px] font-semibold leading-5 truncate">{m.title}</div>
          <div className="text-[12.5px] text-muted truncate">{who >= 0 ? `${hosts[who].name} is speaking` : castLine(m)}</div>
        </div>
        <ShareFile file={m} />
      </div>
      <Scrubber m={m} p={p} />
      <Controls m={m} p={p} />
      <Transcript m={m} p={p} open={open} setOpen={setOpen} />
    </div>
  );
}

/** An audio story: the title and teaser, who's who before it plays (folded to one line while it plays), then the
 * faces with the speaker grown and the line being said, the player, and the transcript. */
function StoryCard({ m }: { m: Media }) {
  const p = usePlayer(m);
  const [transcriptOpen, setTranscriptOpen] = useState(false);
  const [castOpened, setCastOpened] = useState(false);
  const live = p.playing || p.time > 0;
  const words = playerWords(m);
  return (
    <div className="glass rounded-[26px] p-4 w-full max-w-[420px] flex flex-col gap-3" data-media={m.kind} data-ready={p.ready ? "1" : "0"}>
      <div className="flex items-start gap-3">
        <div className="flex-1 min-w-0">
          <div className="text-[11px] uppercase tracking-[0.08em] font-bold text-muted">{words.label}</div>
          <div className="text-[15.5px] font-semibold leading-5 line-clamp-2">{m.title}</div>
          {m.teaser && <p data-teaser="" className="text-[13px] leading-[18px] text-ink-2 mt-1 line-clamp-2">{m.teaser}</p>}
        </div>
        <ShareFile file={m} />
      </div>
      {live && (
        <button onClick={() => setCastOpened(!castOpened)} aria-expanded={castOpened}
          className="text-left text-[12.5px] text-muted truncate -mt-1">
          {castOpened ? "Hide who's who" : castLine(m)}
        </button>
      )}
      {showsWhoIsWho(live, castOpened) && <WhoIsWho m={m} />}
      {live && <StoryStage m={m} time={p.time} playing={p.playing} onOpen={() => setTranscriptOpen(true)} />}
      <Scrubber m={m} p={p} />
      <Controls m={m} p={p} />
      <Transcript m={m} p={p} open={transcriptOpen} setOpen={setTranscriptOpen} />
    </div>
  );
}

/** Who's who in a story: each voice's face, name (in their colour) and who they are. A long cast scrolls inside a
 * capped height, so on a phone it never pushes the player off the screen. */
function WhoIsWho({ m }: { m: Media }) {
  const hosts = m.hosts ?? [];
  return (
    <ul aria-label="Who's who" className="flex flex-col gap-2.5 max-h-[224px] overflow-y-auto pl-1 py-1">
      {hosts.map((h, i) => {
        const role = castRole(h);
        return (
          <li key={h.name} className="flex items-center gap-2.5 min-w-0">
            <FaceAvatar m={m} host={h} i={i} size={30} />
            <span className="text-[13px] leading-[17px] min-w-0">
              <b style={{ color: textToneAt(m, i) }}>{h.name}</b>
              {role && <span className="text-muted"> · {role}</span>}
            </span>
          </li>
        );
      })}
    </ul>
  );
}

/**
 * Decides how big each face is in the row while a story plays: up to eight fit in one row on a phone at 38 px; a
 * bigger cast gets 30 px faces so the row still fits. 6 voices → 38; 10 voices → 30.
 */
function stageFaceSize(count: number): number {
  if (count <= 8) return 38;
  return 30;
}

/** While a story plays: the name of who is talking, then everyone's face in a row, the speaker's grown with its ring
 * lit, and under them the line being said in the speaker's colour with the one before it faded. A tap on the line opens
 * the full transcript. A screen reader hears "Ada: <line>" once, when the line changes. */
export function StoryStage({ m, time, playing, onOpen }: { m: Media; time: number; playing: boolean; onOpen: () => void }) {
  const hosts = m.hosts ?? [];
  const who = speakingAt(m, time);
  const { before, now } = linesAt(m, time);
  const size = stageFaceSize(hosts.length);
  const nowTone = textToneAt(m, Math.max(0, who));
  return (
    <div className="flex flex-col gap-1.5">
      <SpeakerName m={m} time={time} playing={playing} />
      <div className="flex justify-center -space-x-1.5 py-2.5">
        {hosts.map((h, i) => (
          <FaceAvatar key={h.name} m={m} host={h} i={i} size={size} speaking={who === i} onStage />
        ))}
      </div>
      {now && (
        <button onClick={onOpen} aria-label="Show the full transcript" className="text-center rounded-[14px] px-2 py-1 active:bg-well">
          <span aria-hidden className="flex flex-col gap-0.5">
            <span data-line="before" className="text-[12.5px] leading-[17px] text-muted opacity-70 line-clamp-1 min-h-[17px]">{before?.text ?? ""}</span>
            <span data-line="now" className="text-[14.5px] leading-[20px] font-medium line-clamp-3 min-h-[60px]" style={{ color: nowTone }}>{now.text}</span>
          </span>
        </button>
      )}
      <p aria-live="polite" className="sr-only">{now ? `${now.host}: ${now.text}` : ""}</p>
    </div>
  );
}

/** Above a story's faces: who is talking, bold in their colour, with three bars beside the name bouncing like a sound
 * meter. While only sound plays, the last speaker's name stays, dimmed, with the bars still; paused, the bars hold still
 * too; before anyone has spoken the line is empty. It always keeps its height, so the faces never jump. A screen reader
 * skips it: the line under the faces already says "Ada: <line>". */
function SpeakerName({ m, time, playing }: { m: Media; time: number; playing: boolean }) {
  const line = nameLineAt(m, time);
  if (!line) return <div data-speaker-line="" aria-hidden className="h-[22px]" />;
  const name = (m.hosts ?? [])[line.index].name;
  const tone = textToneAt(m, line.index);
  const dimmed = line.talking ? "" : "opacity-50";
  const barsMove = line.talking && playing;
  const talking = barsMove ? "1" : "0";
  return (
    <div data-speaker-line="" aria-hidden style={{ color: tone }}
      className={`h-[22px] flex items-center justify-center gap-2 min-w-0 transition-opacity duration-300 motion-reduce:transition-none ${dimmed}`}>
      <b className="text-[15px] leading-[22px] truncate">{name}</b>
      <span className="talk-bars" data-talking={talking}><i></i><i></i><i></i></span>
    </div>
  );
}

/** One voice's round face with their tone as the ring. On the stage, the speaker's face grows (SPEAKER_SCALE) with
 * the ring lit and drawn over its neighbours; with reduced motion it changes size without the animation. */
function FaceAvatar({ m, host, i, size, speaking = false, onStage = false }:
  { m: Media; host: Host; i: number; size: number; speaking?: boolean; onStage?: boolean }) {
  const tone = toneAt(m, i);
  const idleRing = `0 0 0 2px var(--t-surface-2), 0 0 0 3.5px color-mix(in srgb, ${tone} 60%, transparent)`;
  const litRing = `0 0 0 2px var(--t-surface-2), 0 0 0 4px ${tone}, 0 4px 14px -2px ${tone}`;
  const scale = speaking ? SPEAKER_SCALE : 1;
  const label = speaking ? `${host.name}, speaking` : host.name;
  let speakingMark: string | undefined;  // only faces on the stage say whether they're speaking
  if (onStage) speakingMark = speaking ? "1" : "0";
  return (
    <span role="img" aria-label={label} title={host.name} data-speaking={speakingMark}
      className="shrink-0 rounded-full overflow-hidden relative transition-[transform,box-shadow] duration-300 ease-out motion-reduce:transition-none"
      style={{ width: size, height: size, transform: `scale(${scale})`, zIndex: speaking ? 2 : 1, boxShadow: speaking ? litRing : idleRing }}>
      <Face name={host.name} group={host.group} tone={tone} />
    </span>
  );
}

/** The position bar (a tap jumps there) and the time played and the length. */
function Scrubber({ m, p }: { m: Media; p: Player }) {
  const words = playerWords(m);
  const pct = p.duration ? Math.min(100, (p.time / p.duration) * 100) : 0;
  return (
    <div>
      <div onClick={p.seekAt} role="slider" aria-label={words.position} aria-valuemin={0} aria-valuemax={Math.round(p.duration)} aria-valuenow={Math.round(p.time)}
        className="h-2 rounded-full bg-well cursor-pointer relative overflow-hidden">
        <div className="absolute inset-y-0 left-0 rounded-full bg-ember" style={{ width: `${pct}%` }} />
      </div>
      <div className="flex justify-between text-[12px] text-muted tabular-nums mt-1"><span>{clock(p.time)}</span><span>{clock(p.duration)}</span></div>
    </div>
  );
}

/** Back 15 s, play or pause, forward 15 s. */
function Controls({ m, p }: { m: Media; p: Player }) {
  const words = playerWords(m);
  return (
    <div className="flex items-center justify-center gap-7">
      <button onClick={() => p.seek(p.time - 15)} aria-label="Back 15 seconds" className="w-11 h-11 rounded-full grid place-items-center text-[13px] font-bold text-ink-2 active:bg-well">−15</button>
      <button onClick={p.toggle} aria-label={p.playing ? words.pause : words.play} className="w-14 h-14 rounded-full bg-ember text-on-ember grid place-items-center">
        <PlayPause playing={p.playing} size={24} />
      </button>
      <button onClick={() => p.seek(p.time + 15)} aria-label="Forward 15 seconds" className="w-11 h-11 rounded-full grid place-items-center text-[13px] font-bold text-ink-2 active:bg-well">+15</button>
    </div>
  );
}

/** The transcript by speaker, behind a toggle; a tap on a line jumps there, and the line playing is shaded. */
function Transcript({ m, p, open, setOpen }: { m: Media; p: Player; open: boolean; setOpen: (open: boolean) => void }) {
  const turns = Array.isArray(m.transcript) ? m.transcript : [];
  const hosts = m.hosts ?? [];
  const live = p.playing || p.time > 0;
  const turn = live ? turnAt(m, p.time) : -1;
  const tone = (name: string) => textToneAt(m, Math.max(0, hosts.findIndex((h) => h.name === name)));
  if (turns.length === 0) return null;
  return (
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
  );
}
