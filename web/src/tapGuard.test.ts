import { describe, expect, it } from "vitest";
import { busyWord } from "./needs";
import { createTapGuard } from "./tapGuard";

describe("the tap guard", () => {
  it("ignores taps for 800 ms after the cards change, and counts them again after", () => {
    let t = 10_000;
    const guard = createTapGuard(() => t);
    expect(guard.ok()).toBe(true);  // never changed
    guard.changed();
    t += 300;
    expect(guard.ok()).toBe(false);
    t += 500;
    expect(guard.ok()).toBe(true);
  });

  it("keeps the card busy only for the moves that must not slide", () => {
    expect(busyWord("merge")).toBe("Merging…");
    expect(busyWord("recipe_use")).toBe("Working…");
    expect(busyWord("job_allow")).toBe("Working…");
    expect(busyWord("job_retry")).toBe("Working…");
    expect(busyWord("job_keep")).toBe("Copying…");  // Keep it: the card stays until the copy is done
    expect(busyWord("done_task")).toBe("");
    expect(busyWord("later")).toBe("");
  });
});
