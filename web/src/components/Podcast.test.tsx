// @vitest-environment jsdom
import { readFileSync } from "node:fs";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { CAST_TEXT, CAST_TONES, HOST_TONES, castLine, castMarks, isStory, playerWords, textToneAt, toneAt, type Media } from "../media";
import { Podcast } from "./Podcast";

const pod: Media = {
  id: "fedcba9876543210", kind: "podcast", title: "Our session", mime: "audio/wav", size: 10, created: 1, duration: 9,
  hosts: [{ name: "Host A", group: "female", voice: "Heart" }, { name: "Host B", group: "male", voice: "Michael" }],
  transcript: [{ host: "Host A", text: "Hi", start: 0 }, { host: "Host B", text: "Hello", start: 2.5 }],
};
const names = ["Narrator", "The keeper", "Ada", "Captain", "Witch", "Boy", "Girl", "Ghost", "Fox", "Owl"];
const story: Media = {
  ...pod, id: "0123456789abcdef", title: "The Lighthouse", mime: "audio/mp4", format: "story",
  hosts: names.map((name, i) => ({ name, group: "female", voice: `Voice ${i + 1}` })),
  transcript: names.map((name, i) => ({ host: name, text: `Line ${i}`, start: i * 2 })),
};

describe("the story player", () => {
  it("is the podcast card, saying Audio story and Play story", () => {
    const html = renderToStaticMarkup(<Podcast m={story} />);
    expect(html).toContain("Audio story");
    expect(html).toContain('aria-label="Play story"');
    expect(html).toContain('aria-label="Story position"');
    expect(html).not.toContain("Podcast");
    expect(playerWords(story)).toEqual({ label: "Audio story", play: "Play story", pause: "Pause story", position: "Story position" });
  });

  it("lists the cast with their voices", () => {
    expect(castLine(story)).toBe(names.map((name, i) => `${name} · Voice ${i + 1}`).join(", "));
    const html = renderToStaticMarkup(<Podcast m={story} />);
    expect(html).toContain("Narrator · Voice 1, The keeper · Voice 2");
  });

  it("marks each speaker so two names with one first letter still differ", () => {
    expect(castMarks(story, ["Narrator", "Nell", "The keeper", "Captain Silas Blackwater"])).toEqual(["Na", "Ne", "Ke", "CS"]);
    expect(castMarks(story, ["Nell", "Nelson"])).toEqual(["Ne", "N2"]);  // still the same: a number tells them apart
    expect(castMarks(pod, ["Host A", "Host B"])).toEqual(["A", "B"]);  // a podcast keeps its one letter
    const html = renderToStaticMarkup(<Podcast m={{ ...story, hosts: [{ name: "Narrator", group: "male" }, { name: "Nell", group: "female" }] }} />);
    expect(html).toContain(">Na</span>");
    expect(html).toContain(">Ne</span>");
  });

  it("shows the whole cast under the title, wrapping rather than cut", () => {
    const html = renderToStaticMarkup(<Podcast m={story} />);
    const line = html.match(/<div class="([^"]*)">Narrator · Voice 1/);
    expect(line).not.toBeNull();
    expect(line![1]).not.toContain("truncate");
    expect(renderToStaticMarkup(<Podcast m={pod} />)).toMatch(/class="[^"]*truncate[^"]*">Host A and Host B/);
  });

  it("gives up to eight speakers their own tone, then cycles", () => {
    expect(CAST_TONES).toHaveLength(8);
    expect(new Set(CAST_TONES).size).toBe(8);
    expect(CAST_TONES.slice(0, 2)).toEqual(HOST_TONES);  // a story's first two speakers look like a podcast's hosts
    expect([2, 7].map((i) => toneAt(story, i))).toEqual([CAST_TONES[2], CAST_TONES[7]]);
    expect(toneAt(story, 8)).toBe(CAST_TONES[0]);
    expect(textToneAt(story, 5)).toBe(CAST_TEXT[5]);
    const css = readFileSync("src/styles.css", "utf8")  // vitest runs in web/;
    for (let n = 3; n <= 8; n++) {
      expect(css.match(new RegExp(`--t-cast-${n}: #[0-9A-Fa-f]{6};`, "g"))).toHaveLength(1);
      expect(css.match(new RegExp(`--t-cast-${n}-text: #[0-9A-Fa-f]{6};`, "g"))).toHaveLength(2);  // day and night
    }
  });
});

describe("the podcast player stays as it was", () => {
  it("says Podcast and Play podcast, names its two hosts, and keeps two tones", () => {
    const html = renderToStaticMarkup(<Podcast m={pod} />);
    expect(html).toContain("Podcast");
    expect(html).toContain('aria-label="Play podcast"');
    expect(html).toContain("Host A and Host B");
    expect(isStory(pod)).toBe(false);
    expect(toneAt(pod, 2)).toBe(HOST_TONES[0]);
    expect(castLine(pod)).toBe("Host A and Host B");
  });
});
