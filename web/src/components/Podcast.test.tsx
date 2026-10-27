// @vitest-environment jsdom
import { readFileSync } from "node:fs";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import {
  CAST_TEXT, CAST_TONES, HOST_TONES, SPEAKER_SCALE, castLine, castRole, isStory, linesAt, nameLineAt, playerWords, showsWhoIsWho,
  textToneAt, toneAt, type Media, type Turn,
} from "../media";
import { Podcast, StoryStage } from "./Podcast";

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
const told: Media & { teaser: string } = {
  ...story, title: "Salt and Timber",
  teaser: "A widow restoring the house her husband left on the Oregon coast, and the quiet man hired to fix it.",
  hosts: [{ name: "Claire", group: "female", voice: "Heart", who: "the widow who tells it" },
    { name: "Tom", group: "male", voice: "Michael", who: "the quiet man hired to fix it" }],
  transcript: [{ host: "Claire", text: "The storm came early.", start: 0 }, { host: "Tom", text: "Roof first.", start: 3 }],
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

  it("shows the teaser and who's who before it plays: a face, the name and who they are", () => {
    const html = renderToStaticMarkup(<Podcast m={told} />);
    expect(html).toContain(told.teaser);
    expect(html).toContain("the widow who tells it");
    expect(html).toContain("the quiet man hired to fix it");
    expect(html.match(/data-face="/g)).toHaveLength(2);  // one drawn face per person
    expect(html).not.toContain('aria-live="polite"');  // nothing is being said yet
  });

  it("still shows a story made before teasers: the cast with their voices, and no empty teaser", () => {
    const html = renderToStaticMarkup(<Podcast m={story} />);
    expect(html).toContain("Voice 1");
    expect(html).toContain("The keeper");
    expect(html).not.toContain('data-teaser="');
    expect(html.match(/data-face="/g)).toHaveLength(names.length);
    expect(castRole({ name: "Ada", group: "female" })).toBe("");  // neither who nor voice: just the name
  });

  it("shows who's who until it plays, then folds it to one line unless it's opened again", () => {
    expect(showsWhoIsWho(false, false)).toBe(true);
    expect(showsWhoIsWho(true, false)).toBe(false);
    expect(showsWhoIsWho(true, true)).toBe(true);
    expect(castLine(story)).toBe(names.join(", "));  // the folded line: just the names
  });

  it("grows the speaker's face inside their turn, the others stay small", () => {
    const html = renderToStaticMarkup(<StoryStage m={story} time={4.5} playing onOpen={() => {}} />);  // turn 2: Ada
    const speaking = html.match(/<span[^>]*data-speaking="1"[^>]*>/g) ?? [];
    expect(speaking).toHaveLength(1);
    expect(speaking[0]).toContain('aria-label="Ada, speaking"');
    expect(speaking[0]).toContain(`scale(${SPEAKER_SCALE})`);
    expect(html.match(/scale\(1\.35\)/g)).toHaveLength(1);
    expect(html.match(/data-speaking="0"/g)).toHaveLength(names.length - 1);
    expect(SPEAKER_SCALE).toBe(1.35);
  });

  it("says the current line under the faces, the one before faded, and tells a screen reader once", () => {
    const html = renderToStaticMarkup(<StoryStage m={story} time={4.5} playing onOpen={() => {}} />);
    expect(html).toMatch(/data-line="before"[^>]*>Line 1</);
    expect(html).toMatch(/data-line="now"[^>]*>Line 2</);
    expect(html).toMatch(/aria-live="polite"[^>]*>Ada: Line 2</);
    expect(linesAt(story, 4.5)).toEqual({ before: { host: "The keeper", text: "Line 1", start: 2 }, now: { host: "Ada", text: "Line 2", start: 4 } });
    expect(linesAt(story, 0)).toEqual({ before: null, now: { host: "Narrator", text: "Line 0", start: 0 } });
    expect(linesAt({ ...story, transcript: [] }, 3)).toEqual({ before: null, now: null });
  });

  it("names who is talking above the faces, bold in their colour, with the talking bars moving", () => {
    const html = renderToStaticMarkup(<StoryStage m={story} time={4.5} playing onOpen={() => {}} />);  // turn 2: Ada
    const line = html.match(/<div[^>]*data-speaker-line=""[^>]*>.*?<\/div>/)?.[0] ?? "";
    expect(line).toMatch(/<b[^>]*>Ada<\/b>/);
    expect(line).toContain(`color:${textToneAt(story, 2)}`);
    expect(line).toContain('data-talking="1"');
    expect(line.match(/<i><\/i>/g)).toHaveLength(3);  // three bars
    expect(line).toContain("talk-bars");
    expect(html.indexOf("data-speaker-line")).toBeLessThan(html.indexOf("data-speaking="));  // above the faces
    expect(nameLineAt(story, 4.5)).toEqual({ index: 2, talking: true });
  });

  it("keeps the last speaker's name, dimmed and with still bars, while only sound plays", () => {
    const withSound: Media = { ...told, transcript: [...(told.transcript as Turn[]), { host: "Sound", text: "(waves)", start: 6 }] };
    const html = renderToStaticMarkup(<StoryStage m={withSound} time={7} playing onOpen={() => {}} />);
    const line = html.match(/<div[^>]*data-speaker-line=""[^>]*>.*?<\/div>/)?.[0] ?? "";
    expect(line).toMatch(/<b[^>]*>Tom<\/b>/);
    expect(line).toContain('data-talking="0"');
    expect(line).toContain("opacity-50");
    expect(nameLineAt(withSound, 7)).toEqual({ index: 1, talking: false });
  });

  it("holds the bars still while paused, the name still in full colour", () => {
    const html = renderToStaticMarkup(<StoryStage m={story} time={4.5} playing={false} onOpen={() => {}} />);
    const line = html.match(/<div[^>]*data-speaker-line=""[^>]*>.*?<\/div>/)?.[0] ?? "";
    expect(line).toMatch(/<b[^>]*>Ada<\/b>/);
    expect(line).toContain('data-talking="0"');
    expect(line).not.toContain("opacity-50");
  });

  it("shows no name in the first seconds, but keeps the line's height so nothing jumps", () => {
    const late: Media = { ...told, transcript: [{ host: "Sound", text: "(rain)", start: 0 }, { host: "Claire", text: "Hello.", start: 3 }] };
    expect(nameLineAt(late, 1)).toBeNull();  // only rain so far
    expect(nameLineAt({ ...told, transcript: [{ host: "Claire", text: "Hi", start: 2 }] }, 0.5)).toBeNull();  // before the first line
    const html = renderToStaticMarkup(<StoryStage m={late} time={1} playing onOpen={() => {}} />);
    const line = html.match(/<div[^>]*data-speaker-line=""[^>]*>.*?<\/div>/)?.[0] ?? "";
    expect(line).toContain("h-[22px]");
    expect(line).not.toContain("<b");
    expect(line).not.toContain("talk-bars");
  });

  it("lets a screen reader hear the name once, with the line, not from the name above the faces", () => {
    const html = renderToStaticMarkup(<StoryStage m={story} time={4.5} playing onOpen={() => {}} />);
    expect(html).toMatch(/<div[^>]*data-speaker-line=""[^>]*aria-hidden="true"/);
    expect(html).toMatch(/aria-live="polite"[^>]*>Ada: Line 2</);
    expect(html.match(/aria-live=/g)).toHaveLength(1);
  });

  it("bounces the bars only while someone talks, and holds them still with reduced motion", () => {
    const css = readFileSync("src/styles.css", "utf8");
    expect(css).toMatch(/@keyframes talk-bars/);
    expect(css).toMatch(/\.talk-bars\[data-talking="0"\] i \{[^}]*animation: none/);
    const reduced = css.match(/@media \(prefers-reduced-motion: reduce\) \{[^}]*\.talk-bars i[^}]*\}/);
    expect(reduced?.[0]).toContain("animation: none");
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
    expect(html).toMatch(/class="[^"]*truncate[^"]*">Host A and Host B/);
    expect(html).toContain(">A</span>");  // its hosts keep their coloured letters
    expect(html).toContain(">B</span>");
    expect(html).toContain("w-11 h-11 rounded-full");  // the same letter avatars as before
    expect(html).not.toContain("data-face=");  // no drawn faces on a podcast
    expect(html).not.toContain('aria-live="polite"');
    expect(html).not.toContain("data-speaker-line");  // no name line or talking bars on a podcast
    expect(html).not.toContain("talk-bars");
  });
});
