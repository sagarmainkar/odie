import type { Media } from "../media";
import { groupMedia, liveShot } from "../screenshots";
import { DeckCard } from "./DeckCard";
import { FileCard } from "./FileCard";
import { AudioCard, PictureCard, VideoCard } from "./InlineMedia";
import { Podcast } from "./Podcast";
import { LiveBrowser, ScreenshotStrip } from "./Screenshots";
import { TrackerSignInCard } from "./TrackerSignInCard";
import { PayCard, TurnCard } from "./TurnCard";
import { VoiceMemo } from "./VoiceMemo";

/** What tools made for this reply, drawn by kind. `live`: the reply is still being written, so the browser's latest
 * page shows large; afterwards its pages fold into a strip. */
export function MediaList({ items, live = false, autoplay }: { items: Media[]; live?: boolean; autoplay?: string }) {
  const { shots, rest } = groupMedia(items);
  const now = liveShot(items, live);
  return (
    <div className="flex flex-col gap-2.5">
      {now ? <LiveBrowser shot={now} count={shots.length} /> : shots.length > 0 && <ScreenshotStrip shots={shots} />}
      {rest.map((m) => (m.kind === "memo" ? <VoiceMemo key={m.id} m={m} autoPlay={m.id === autoplay} /> : m.kind === "podcast" ? <Podcast key={m.id} m={m} />
        : m.kind === "file" && m.deck ? <DeckCard key={m.id} m={m} /> : m.kind === "file" ? <FileCard key={m.id} m={m} />
        : m.kind === "picture" ? <PictureCard key={m.id} m={m} /> : m.kind === "video" ? <VideoCard key={m.id} m={m} /> : m.kind === "audio" ? <AudioCard key={m.id} m={m} />
        : m.kind === "turn" ? <TurnCard key={m.id} m={m} /> : m.kind === "link" ? <PayCard key={m.id} m={m} /> : m.kind === "tracker" ? <TrackerSignInCard key={m.id} m={m} /> : null))}
    </div>
  );
}
