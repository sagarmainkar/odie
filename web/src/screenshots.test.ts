import { describe, expect, it } from "vitest";
import type { Media } from "./media";
import { groupMedia, liveShot, site, watchTab } from "./screenshots";

const shot = (id: string, url: string): Media => ({ id, kind: "screenshot", title: url, mime: "image/jpeg", size: 1, created: 1, url, step: "Opened" });
const memo: Media = { id: "m", kind: "memo", title: "Memo", mime: "audio/wav", size: 1, created: 1 };
const pod: Media = { id: "p", kind: "podcast", title: "Pod", mime: "audio/wav", size: 1, created: 1 };

describe("screenshots", () => {
  it("names a page by its site", () => {
    expect(site("https://www.amazon.in/s?k=airpods")).toBe("amazon.in");
    expect(site("http://example.com:8080/a")).toBe("example.com");
    expect(site("not a url")).toBe("not a url");
  });

  it("keeps the screenshots together and the players apart", () => {
    const a = shot("a", "https://www.amazon.in/"), b = shot("b", "https://www.flipkart.com/");
    expect(groupMedia([memo, a, pod, b])).toEqual({ shots: [a, b], rest: [memo, pod] });
    expect(groupMedia([memo])).toEqual({ shots: [], rest: [memo] });
  });

  it("shows the latest page large while the reply is being written", () => {
    const a = shot("a", "https://www.amazon.in/"), b = shot("b", "https://www.amazon.in/dp/1");
    expect(liveShot([a, memo, b], true)).toBe(b);
    expect(liveShot([a, b], false)).toBeNull();
    expect(liveShot([memo], true)).toBeNull();
  });

  it("opens the tab the latest page is in, and only when the live view exists", () => {
    const old = shot("a", "https://www.amazon.in/");  // taken before screenshots carried their tab
    const fresh: Media = { ...shot("b", "https://www.amazon.in/dp/1"), tab: "chat-2026-11-17" };
    expect(watchTab([old, fresh], "chat-2026-11-02", true)).toBe("chat-2026-11-17");
    expect(watchTab([old], "chat-2026-11-02", true)).toBe("chat-2026-11-02");
    expect(watchTab([old], undefined, true)).toBeUndefined();
    expect(watchTab([], "chat-2026-11-02", true)).toBeUndefined();
    expect(watchTab([fresh], "chat-2026-11-17", false)).toBeUndefined();  // signed-in browsing is off: no Watch
  });
});
