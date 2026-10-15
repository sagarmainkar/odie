import { useState } from "react";
import { dismissNudge, isPhone, isStandalone, nudgeDismissed, shouldNudge } from "../install";
import { Icon, Tile } from "./Tile";

/** Today, in a phone's browser: add Odie to the Home Screen (full screen, notifications, links open neatly). */
export function InstallNudge() {
  const [show, setShow] = useState(() => shouldNudge({ standalone: isStandalone(), phone: isPhone(), dismissed: nudgeDismissed() }));
  if (!show) return null;
  const iphone = /iPhone|iPod/i.test(navigator.userAgent);
  return (
    <div className="glass rounded-[22px] px-3.5 py-3 flex items-start gap-3 rise">
      <Tile icon="spark" color="blue" small />
      <div className="flex-1 min-w-0">
        <div className="text-[14.5px] font-semibold leading-5">Add Odie to your Home Screen</div>
        <div className="text-[13px] leading-[18px] text-muted">
          Full screen, notifications, and links open neatly. {iphone ? "Tap Share, then Add to Home Screen, and open Odie from its icon." : "Open the browser menu, then Add to Home screen, and open Odie from its icon."}
        </div>
      </div>
      <button aria-label="Hide" onClick={() => { dismissNudge(); setShow(false); }} className="pill pill-flat w-8 h-8 px-0 shrink-0"><Icon name="x" size={14} /></button>
    </div>
  );
}
