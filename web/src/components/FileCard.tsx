import { useState } from "react";
import { kindOf, size, typeLabel, type FileKind } from "../files";
import { mediaUrl, type Media } from "../media";
import { opensInReader } from "../reader";
import { ReportReader } from "./ReportReader";
import { ShareFile } from "./ShareButton";
import { Icon, Tile, type IconName, type TileColor } from "./Tile";

const LOOK: Record<FileKind, [IconName, TileColor]> = {
  slides: ["chart", "orange"], doc: ["note", "blue"], pdf: ["note", "pink"], sheet: ["chart", "green"], web: ["globe", "violet"], calendar: ["cal", "pink"],
  data: ["terminal", "ink"], text: ["note", "yellow"], picture: ["photo", "orange"], video: ["play", "pink"], audio: ["speaker", "violet"], other: ["copy", "ink"],
};

/** A file the assistant attached: its type, name and size, the download, and the share sheet where the browser has one.
 * A Markdown or text file (a research report) opens in the reader instead, where Download is too. */
export function FileCard({ m }: { m: Media }) {
  const name = m.filename || m.title;
  const kind = kindOf(name);
  const [icon, color] = LOOK[kind];
  const [reading, setReading] = useState(false);
  if (opensInReader(name)) {
    return (
      <div data-media="file" className="glass rounded-tile flex items-center gap-2 pl-3.5 pr-3 py-3 w-full max-w-[380px]">
        <button type="button" onClick={() => setReading(true)} aria-label={`Read ${name}, ${typeLabel(kind)}, ${size(m.size)}`}
          className="flex-1 min-w-0 flex items-center gap-3 text-left active:opacity-70">
          <Tile icon={icon} color={color} small />
          <span className="flex-1 min-w-0">
            <b className="block text-ui font-semibold leading-5 truncate">{name}</b>
            <span className="block text-small text-muted">{typeLabel(kind)} · {size(m.size)}</span>
          </span>
          <span className="pill pill-solid shrink-0 h-9 px-3.5 text-small font-semibold shadow-none">Read</span>
        </button>
        <ShareFile file={m} />
        {reading && <ReportReader m={m} onClose={() => setReading(false)} />}
      </div>
    );
  }
  return (
    <div data-media="file" className="glass rounded-tile flex items-center gap-2 pl-3.5 pr-3 py-3 w-full max-w-[380px]">
      <a href={mediaUrl(m)} download={name} aria-label={`Download ${name}, ${typeLabel(kind)}, ${size(m.size)}`}
        className="flex-1 min-w-0 flex items-center gap-3 active:opacity-70">
        <Tile icon={icon} color={color} small />
        <span className="flex-1 min-w-0">
          <b className="block text-ui font-semibold leading-5 truncate">{name}</b>
          <span className="block text-small text-muted">{typeLabel(kind)} · {size(m.size)}</span>
        </span>
        <span className="shrink-0 w-9 h-9 rounded-full bg-well grid place-items-center text-ink-2 rotate-180"><Icon name="up" size={17} /></span>
      </a>
      <ShareFile file={m} />
    </div>
  );
}
