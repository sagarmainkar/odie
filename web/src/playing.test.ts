import { describe, expect, it } from "vitest";
import { markPlaying, markStopped, setTalking, somethingPlaying } from "./playing";

describe("what's playing", () => {
  it("tracks the player that's on, and forgets it once it stops or goes away", () => {
    expect(somethingPlaying()).toBe(false);
    markPlaying("a");
    expect(somethingPlaying()).toBe(true);
    markStopped("b");  // another player stopping doesn't clear this one
    expect(somethingPlaying()).toBe(true);
    markStopped("a");  // also what a player does when it unmounts mid-play
    expect(somethingPlaying()).toBe(false);
  });

  it("counts a Talk session as something playing", () => {
    setTalking(true);
    expect(somethingPlaying()).toBe(true);
    setTalking(false);
    expect(somethingPlaying()).toBe(false);
  });
});
