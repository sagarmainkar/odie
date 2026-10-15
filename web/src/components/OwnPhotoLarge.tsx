import { useEffect, useState } from "react";
import { getJSON, postJSON } from "../api";
import { originalUrl, viewFor, type OwnInfo } from "../ownPhoto";

/** The large view of one of Odie's own photos or videos. A video's original is fetched from iCloud on Play
 * (ownPhoto.ts says what to show at each step); the poll runs every two seconds while Photos downloads it. */
export function OwnPhotoLarge({ uuid, big, caption }: { uuid: string; big: string; caption?: string }) {
  const [info, setInfo] = useState<OwnInfo | null>(null);
  useEffect(() => {
    let live = true;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const load = () => getJSON<OwnInfo>(`/api/photos/${uuid}/info`).then((x) => {
      if (!live) return;
      setInfo(x);
      if (x.original.state === "fetching") timer = setTimeout(load, 2000);
    }).catch(() => {});
    load();
    return () => { live = false; clearTimeout(timer); };
  }, [uuid]);
  async function play(e: React.MouseEvent) {
    e.stopPropagation();
    try {
      const o = await postJSON<OwnInfo["original"]>(`/api/photos/${uuid}/fetch`, {});
      setInfo((x) => (x ? { ...x, original: o } : x));
      if (o.state === "fetching") {
        const poll = async () => {
          const s = await getJSON<OwnInfo["original"]>(`/api/photos/${uuid}/fetch`).catch(() => null);
          if (!s) return;
          setInfo((x) => (x ? { ...x, original: s } : x));
          if (s.state === "fetching") setTimeout(poll, 2000);
        };
        setTimeout(poll, 2000);
      }
    } catch { /* the view keeps what it showed */ }
  }
  const view = info ? viewFor(info) : null;
  const stop = (e: React.MouseEvent) => e.stopPropagation();
  if (view?.show === "video") {
    return (
      <div onClick={stop} className="flex flex-col items-center max-w-full">
        <video src={originalUrl(uuid)} controls autoPlay playsInline className="max-w-full max-h-[78vh] rounded-[28px] bg-black" />
        {caption && <div className="mt-3 text-center text-[14px] text-white/85">{caption}</div>}
      </div>
    );
  }
  return (
    <div className="flex flex-col items-center max-w-full">
      <div className="relative">
        <img src={big} alt={caption ?? ""} className="max-w-full max-h-[78vh] object-contain rounded-[28px]" />
        {view?.button && (
          <button type="button" onClick={play} aria-label={view.button} onPointerDown={stop}
            className="absolute inset-0 m-auto w-20 h-20 rounded-full bg-white/90 text-ink grid place-items-center text-[15px] font-semibold shadow-lg active:scale-95">
            {view.button === "Play" ? <svg width="30" height="30" viewBox="0 0 24 24" fill="currentColor" aria-hidden><path d="M8 5v14l11-7z" /></svg> : "Retry"}
          </button>
        )}
      </div>
      {(caption || view?.note) && (
        <div className="mt-3 text-center text-[14px] text-white/85">{caption}{view?.note ? <span className="block text-[13px] text-white/70 mt-1">{view.note}</span> : null}</div>
      )}
    </div>
  );
}
