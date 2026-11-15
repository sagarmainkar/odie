import { useState } from "react";
import { LiveView } from "./LiveView";
import { TeamCard } from "./TeamCard";
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
export function MediaList({ items, live = false, autoplay, tab: chatTab }: { items: Media[]; live?: boolean; autoplay?: string; tab?: string }) {
  const { shots, rest } = groupMedia(items);
  const now = liveShot(items, live);
  // Odie's browser tab for these pages (saved with each screenshot), else the chat's: Watch opens it live. The view
  // lives here, not in the live preview, so it stays open when the answer finishes and the preview becomes a strip.
  const last = shots.length ? shots[shots.length - 1] : null;
  const tab = last?.tab ?? chatTab;
  const [watching, setWatching] = useState(false);
  const openLive = tab ? () => setWatching(true) : undefined;
  return (
    <div className="flex flex-col gap-2.5">
      {now ? <LiveBrowser shot={now} count={shots.length} onWatch={openLive} /> : shots.length > 0 && <ScreenshotStrip shots={shots} onOpenLive={openLive} />}
      {watching && tab && <LiveView tab={tab} site={siteOf(last?.url ?? "")} chat={false} watch who="Odie" onClose={() => setWatching(false)} />}
      {rest.map((m) => (m.kind === "memo" ? <VoiceMemo key={m.id} m={m} autoPlay={m.id === autoplay} /> : m.kind === "podcast" ? <Podcast key={m.id} m={m} />
        : m.kind === "file" && m.deck ? <DeckCard key={m.id} m={m} /> : m.kind === "file" ? <FileCard key={m.id} m={m} />
        : m.kind === "picture" ? <PictureCard key={m.id} m={m} /> : m.kind === "video" ? <VideoCard key={m.id} m={m} /> : m.kind === "audio" ? <AudioCard key={m.id} m={m} />
        : m.kind === "turn" ? <TurnCard key={m.id} m={m} /> : m.kind === "link" ? <PayCard key={m.id} m={m} /> : m.kind === "tracker" ? <TrackerSignInCard key={m.id} m={m} /> : m.kind === "team" && m.job ? <TeamCard key={m.id} job={m.job} /> : null))}
    </div>
  );
}

/** A page's site for the live view's bar: "https://www.flipkart.com/x" -> "flipkart.com"; nothing -> "". */
function siteOf(url: string): string {
  try { return new URL(url).host.replace(/^www\./, ""); } catch { return ""; }
}
