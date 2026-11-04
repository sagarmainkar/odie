// @vitest-environment jsdom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { renderToStaticMarkup } from "react-dom/server";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { getJSON } from "../api";
import type { MorningCard as Card, MorningReply } from "../morning";
import { useMorning } from "../useMorning";
import { MorningCard, MorningHello } from "./MorningCard";

vi.mock("../api", async (real) => ({ ...(await real<typeof import("../api")>()), getJSON: vi.fn(async () => ({})) }));
(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const card: Card = {
  greeting: "Morning, Asha. Four days to Diwali", accent: "Diwali", emoji: "🪔",
  say: ["How was the play last night? I hope Dev liked it.", "Yesterday we got the reporter running. Start there?"],
  weather: { place: "Pune", now_c: 27, high_c: 31, low_c: 19, words: "Clear" },
  tiles: [
    { label: "Today", value: "2 events", note: "Review 11:00 · Dentist 16:30" },
    { label: "Due soon", value: "₹1,179", note: "Phone bill, Friday" },
  ],
  nudge: { icon: "🎂", text: "Dev turns 7 on 13 Nov. Gift ideas?" },
  mail: [{ icon: "↩️", title: "Order cancelled", note: "Refund in 5–7 days", pill: "" },
    { icon: "🏦", title: "Card statement", note: "Due 15 Nov", pill: "11 days" }],
  recent: [{ state: "done", text: "Workers spike step 1 built", note: "" },
    { state: "stuck", text: "Mail reporter times out", note: "Still open" },
    { state: "open", text: "Mac app price", note: "Not decided" }],
  chips: ["Plan my day", "Fix the reporter"],
  day: "2026-11-04", made_at: "2026-11-04T07:31:12+05:30", fallback: false,
};

const fallback: Card = {
  ...card, greeting: "Good morning, Asha.", accent: "", emoji: "", say: [], weather: null, nudge: null,
  mail: [], recent: [], chips: [], fallback: true,
};

const draw = (c: Card) => renderToStaticMarkup(<MorningCard card={c} onChip={() => {}} />);

async function mount(node: React.ReactNode) {
  const host = document.createElement("div");
  document.body.appendChild(host);
  const root = createRoot(host);
  await act(async () => root.render(node));
  return { host, root, done: () => act(() => root.unmount()) };
}

describe("the morning hello card", () => {
  it("draws Odie's words, the weather, the tiles, the nudge and each row", () => {
    const html = draw(card);
    expect(html).toContain('<span class="serif');  // the accent word in serif italic
    expect(html).toContain("Diwali</span>");
    expect(html).toContain("🪔");
    expect(html).toContain("How was the play last night?");
    expect(html).toContain("Yesterday we got the reporter running.");
    expect(html).toContain("27°");
    expect(html).toContain("Clear in Pune");
    expect(html).toContain("19° tonight");
    expect(html).toContain("₹1,179");
    expect(html).toContain("Review 11:00 · Dentist 16:30");
    expect(html).toContain("Dev turns 7 on 13 Nov. Gift ideas?");
    expect(html).toContain("From your mail");
    expect(html).toContain("Order cancelled");
    expect(html).toContain("11 days");
    expect(html).toContain("Last few days");
    expect(html).toContain("Mail reporter times out");
    expect(html).toContain("Not decided");
    expect(html).toContain("Plan my day");
  });

  it("marks the last few days as done, stuck or open", () => {
    const html = draw(card);
    expect(html).toContain('aria-label="Done"');
    expect(html).toContain('aria-label="Stuck"');
    expect(html).toContain('aria-label="Open"');
  });

  it("draws the parts in B1's order", () => {
    const html = draw(card);
    const order = ["Morning, Asha", "How was the play", "Clear in Pune", "2 events", "Dev turns 7", "From your mail", "Last few days", "Plan my day"];
    const places = order.map((words) => html.indexOf(words));
    expect(places.every((p) => p >= 0)).toBe(true);
    expect([...places].sort((a, b) => a - b)).toEqual(places);
  });

  it("draws a row whose state it doesn't know as open, instead of breaking", () => {
    const odd = { state: "maybe", text: "Pick a name for the app", note: "" } as unknown as Card["recent"][number];
    const html = draw({ ...card, recent: [odd] });
    expect(html).toContain("Pick a name for the app");
    expect(html).toContain('aria-label="Open"');
  });

  it("skips a part that is empty: no mail, no section", () => {
    const html = draw({ ...card, mail: [] });
    expect(html).not.toContain("From your mail");
    expect(html).toContain("Last few days");
  });

  it("still draws a fallback card's greeting and tiles, with no paragraphs, rows or chips", () => {
    const html = draw(fallback);
    expect(html).toContain("Good morning, Asha.");
    expect(html).not.toContain('<span class="serif');
    expect(html).toContain("2 events");
    expect(html).toContain("₹1,179");
    expect(html).not.toContain("<p class");  // no paragraphs ("<path" is the orb)
    expect(html).not.toContain("°");
    expect(html).not.toContain("Last few days");
    expect(html).not.toContain("<button");
  });

  it("sends a chip's words as the user's message when it's tapped", async () => {
    const onChip = vi.fn();
    const { host, done } = await mount(<MorningCard card={card} onChip={onChip} />);
    const chip = [...host.querySelectorAll("button")].find((b) => b.textContent === "Fix the reporter")!;
    await act(async () => chip.click());
    expect(onChip).toHaveBeenCalledWith("Fix the reporter");
    await done();
  });

  it("says it's getting the day ready while the hello is made, and nothing for none", () => {
    const making: MorningReply = { state: "making", day: "2026-11-04", card: null };
    expect(renderToStaticMarkup(<MorningHello reply={making} onChip={() => {}} />)).toContain("Getting your day ready…");
    const none: MorningReply = { state: "none", day: "2026-11-04", card: null };
    expect(renderToStaticMarkup(<MorningHello reply={none} onChip={() => {}} />)).toBe("");
  });
});

describe("asking for the morning hello", () => {
  const asked = vi.mocked(getJSON);
  const morningAsks = () => asked.mock.calls.filter(([url]) => url === "/api/morning").length;
  function Probe({ threadId }: { threadId: string | null }) {
    const reply = useMorning(threadId);
    return <span>{reply?.state ?? "nothing"}</span>;
  }
  const answer = (state: MorningReply["state"]) => {
    asked.mockImplementation(async (url: string) => (url === "/api/morning" ? { state, day: "2026-11-04", card: state === "ready" ? card : null } : {}));
  };

  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date(2026, 10, 4, 7, 40));
    asked.mockClear();
  });
  afterEach(() => { vi.useRealTimers(); });

  it("asks every 10 seconds while it's being made, and shows the card once it's ready", async () => {
    answer("making");
    const { host, done } = await mount(<Probe threadId={null} />);
    expect(host.textContent).toBe("making");
    expect(morningAsks()).toBe(1);
    await act(async () => { await vi.advanceTimersByTimeAsync(10_000); });
    expect(morningAsks()).toBe(2);
    answer("ready");
    await act(async () => { await vi.advanceTimersByTimeAsync(10_000); });
    expect(host.textContent).toBe("ready");
    await act(async () => { await vi.advanceTimersByTimeAsync(60_000); });
    expect(morningAsks()).toBe(3);  // ready: no more asking
    await done();
  });

  it("keeps asking for three minutes of making, then gives up, stops asking and draws nothing", async () => {
    answer("making");
    const { host, done } = await mount(<Probe threadId={null} />);
    await act(async () => { await vi.advanceTimersByTimeAsync(175_000); });
    expect(morningAsks()).toBe(18);  // at 0, 10, … 170 s
    expect(host.textContent).toBe("making");
    await act(async () => { await vi.advanceTimersByTimeAsync(10_000); });
    expect(morningAsks()).toBe(19);  // the ask at 180 s is the last
    expect(host.textContent).toBe("nothing");
    await act(async () => { await vi.advanceTimersByTimeAsync(10 * 60_000); });
    expect(morningAsks()).toBe(19);  // flat from then on
    await done();
  });

  it("stops asking when the chat closes or an old thread opens", async () => {
    answer("making");
    const { host, root, done } = await mount(<Probe threadId={null} />);
    await act(async () => root.render(<Probe threadId="chat-2026-10-30-5" />));
    expect(host.textContent).toBe("nothing");
    const before = morningAsks();
    await act(async () => { await vi.advanceTimersByTimeAsync(30_000); });
    expect(morningAsks()).toBe(before);

    await act(async () => root.render(<Probe threadId={null} />));
    const reopened = morningAsks();
    await done();
    await act(async () => { await vi.advanceTimersByTimeAsync(30_000); });
    expect(morningAsks()).toBe(reopened);
  });

  it("never asks from an old thread or a later segment of today", async () => {
    answer("ready");
    const { host, root, done } = await mount(<Probe threadId="chat-2026-10-30-5" />);
    expect(morningAsks()).toBe(0);
    expect(host.textContent).toBe("nothing");
    await act(async () => root.render(<Probe threadId="chat-2026-11-04-2" />));
    expect(morningAsks()).toBe(0);
    expect(host.textContent).toBe("nothing");
    await done();
  });
});
