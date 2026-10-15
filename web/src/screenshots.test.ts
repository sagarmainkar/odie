import { describe, expect, it } from "vitest";
import type { Media } from "./media";
import { groupMedia, liveShot, site } from "./screenshots";

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
});
