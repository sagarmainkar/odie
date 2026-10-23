import { describe, expect, it } from "vitest";
import { badge, chatAbout, footer, notOnTheCard, watchRow, type WatchCardData } from "./watch";

const card = (over: Partial<WatchCardData> = {}): WatchCardData => ({
  checked_at: "2026-10-08T14:30:00+05:30", line: "2 new emails", needs_you: [], events: [], unseen: 0,
  sources: { "mail:zapier": { ok: true, app: "Zapier", kind: "mail" }, "calendar:zapier": { ok: true, app: "Zapier", kind: "calendar" } }, ...over,
});

describe("watch", () => {
  it("says when it checked, through what, and when it checks next", () => {
    expect(footer(card(), new Date("2026-10-08T14:31:00+05:30"))).toBe("checked 14:30 via Zapier · next 15:00");
  });
  it("says what's failing instead", () => {
    const c = card({ sources: { "mail:zapier": { ok: false, app: "Zapier", kind: "mail", reason: "401 Unauthorized" } } });
    expect(footer(c, new Date())).toBe("Zapier (mail): 401 Unauthorized");
  });
  it("counts up to 9+", () => {
    expect(badge(0)).toBe("");
    expect(badge(3)).toBe("3");
    expect(badge(12)).toBe("9+");
  });
  it("opens chat about an item", () => {
    expect(chatAbout({ ref: "mail:1", title: "Invoice due Friday", why: "", at: "" })).toBe("Tell me about: Invoice due Friday");
  });
});

describe("watchRow", () => {
  const base = { ref: "mail:1", title: "Invoice due Friday", why: "₹2,480 by the 10th", at: "2026-10-08T14:01:00+05:30", when: "2026-10-08T14:00:00+05:30" };
  it("draws a mail item as the chat's mail row and opens the email on tap", () => {
    const row = watchRow({ ...base, from: "Priya Nair", subject: "Lease renewal", gist: "Sign by Friday please." }, "2026-10-08");
    expect(row.title).toBe("Priya Nair · Lease renewal");
    expect(row.subtitle).toBe(":badge[New]{good} ₹2,480 by the 10th");  // the model's reason; New until Today was opened
    expect(row.lead).toMatchObject({ kind: "initial", letter: "P" });
    expect(row.value).toBe("14:00");
    expect(row.run).toBe("Open the email from Priya Nair about Lease renewal (id 1)");
  });
  it("the tap names the app that holds the mail and its id, so chat reads it there", () => {
    const mail = { ...base, ref: "mail:18f3a2", from: "Priya Nair", subject: "Lease renewal" };
    expect(watchRow({ ...mail, app: "Mail Connector" }, "2026-10-08").run)
      .toBe("Open the email from Priya Nair about Lease renewal (in Mail Connector, id 18f3a2)");
    // an item saved before items named their app: its one badge says where it is; two badges can't say which holds the id
    const one = [{ kind: "app", app: "Mail Connector" }];
    expect(watchRow({ ...mail, badges: one }, "2026-10-08").run).toContain("(in Mail Connector, id 18f3a2)");
    const two = [{ kind: "app", app: "Mail Connector" }, { kind: "icloud", app: "Apple Mail" }];
    expect(watchRow({ ...mail, badges: two }, "2026-10-08").run).toContain("(id 18f3a2)");
  });
  it("a seen item loses the pill; a mail from another day shows its day; no reason falls back to the gist", () => {
    const row = watchRow({ ...base, why: "", from: "CDSL", subject: "Demat alert", gist: "A transaction was reported.", seen: true, when: "2026-10-06T09:00:00+05:30" }, "2026-10-08");
    expect(row.subtitle).toBe("A transaction was reported.");
    expect(row.value).toBe("Tue");
  });
  it("an older item or an event keeps the model's title and asks about it", () => {
    const mail = watchRow({ ...base, seen: true }, "2026-10-08");
    expect(mail.title).toBe("Invoice due Friday");
    expect(mail.lead).toEqual({ kind: "tile", icon: "mail", color: "blue" });
    expect(mail.run).toBe("Tell me about: Invoice due Friday");
    const event = watchRow({ ...base, ref: "event:e1", title: "Standup moved to 3", seen: true }, "2026-10-08");
    expect(event.lead).toEqual({ kind: "tile", icon: "cal", color: "orange" });
  });
  it("leaves out of Today's tasks the watch's threads its card already shows", () => {
    const c = card({ needs_you: [{ ref: "mail:r1", title: "Reply to Asha", why: "she asked twice", at: "" }] });
    const tasks = [
      { id: 1, source_kind: "watch", source_ref: "mail:r1" },  // the same reply, on the card
      { id: 2, source_kind: "watch", source_ref: "mail:o1" },  // an order the card doesn't show
      { id: 3, source_kind: null, source_ref: null },          // the user's own
    ];
    expect(notOnTheCard(tasks, c).map((t) => t.id)).toEqual([2, 3]);
    expect(notOnTheCard(tasks, null).map((t) => t.id)).toEqual([1, 2, 3]);
  });
});
