import { kindOf, size, typeLabel, type FileKind } from "../files";
import { mediaUrl, type Media } from "../media";
import { Icon, Tile, type IconName, type TileColor } from "./Tile";

const LOOK: Record<FileKind, [IconName, TileColor]> = {
  slides: ["chart", "orange"], doc: ["note", "blue"], pdf: ["note", "pink"], sheet: ["chart", "green"], web: ["globe", "violet"], calendar: ["cal", "pink"],
  data: ["terminal", "ink"], text: ["note", "yellow"], picture: ["photo", "orange"], video: ["play", "pink"], audio: ["speaker", "violet"], other: ["copy", "ink"],
};

/** A file the assistant attached: its type, name and size, and the download. */
export function FileCard({ m }: { m: Media }) {
  const name = m.filename || m.title;
  const kind = kindOf(name);
  const [icon, color] = LOOK[kind];
  return (
    <a href={mediaUrl(m)} download={name} data-media="file" aria-label={`Download ${name}, ${typeLabel(kind)}, ${size(m.size)}`}
      className="glass rounded-[20px] flex items-center gap-3 px-3.5 py-3 w-full max-w-[380px] active:bg-well">
      <Tile icon={icon} color={color} small />
      <span className="flex-1 min-w-0">
        <b className="block text-[14.5px] font-semibold leading-5 truncate">{name}</b>
        <span className="block text-[12.5px] text-muted">{typeLabel(kind)} · {size(m.size)}</span>
      </span>
      <span className="shrink-0 w-9 h-9 rounded-full bg-well grid place-items-center text-ink-2 rotate-180"><Icon name="up" size={17} /></span>
    </a>
  );
}
