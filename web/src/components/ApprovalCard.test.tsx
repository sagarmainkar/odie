// @vitest-environment jsdom
import { act, useState } from "react";
import { createRoot } from "react-dom/client";
import { describe, expect, it, vi } from "vitest";
import { getJSON, postJSON } from "../api";
import { forgetMode } from "../approvalsMode";
import { answered } from "../approvals";
import { ChatApproval, type Approval } from "./ApprovalCard";

vi.mock("../api", async (real) => ({ ...(await real<typeof import("../api")>()), postJSON: vi.fn(), getJSON: vi.fn() }));
(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const decidedAt = new Date(2026, 10, 5, 12, 1).toISOString();  // 12:01 in this computer's own time zone
const card: Approval = {
  id: 7, tool: "run_shell", summary: "Run a command", status: "pending", risk: "ok",
  detail: { command: "rm -rf ~/old-notes", cwd: "/Users/asha" }, decided_at: null,
};

async function mount(node: React.ReactNode) {
  const host = document.createElement("div");
  document.body.appendChild(host);
  const root = createRoot(host);
  await act(async () => root.render(node));
  return { host, root, show: (next: React.ReactNode) => act(async () => root.render(next)), done: () => act(() => root.unmount()) };
}

describe("a card in the chat", () => {
  it("shrinks an allowed card to 'You allowed · time' with no command and nothing to tap", async () => {
    const view = await mount(<ChatApproval a={{ ...card, status: "approved", decided_at: decidedAt }} />);
    expect(view.host.textContent).toBe("✓You allowed · 12:01");
    expect(view.host.textContent).not.toContain("rm -rf");
    expect(view.host.querySelector("button")).toBeNull();
    await view.done();
  });

  it("shrinks a refused card to 'You said no · time'", async () => {
    const view = await mount(<ChatApproval a={{ ...card, status: "rejected", decided_at: decidedAt }} />);
    expect(view.host.textContent).toBe("✕You said no · 12:01");
    expect(view.host.textContent).not.toContain("rm -rf");
    expect(view.host.querySelector("button")).toBeNull();
    await view.done();
  });

  it("shrinks a lapsed card to 'Lapsed', without a time", async () => {
    const view = await mount(<ChatApproval a={{ ...card, status: "expired", decided_at: decidedAt }} />);
    expect(view.host.textContent).toBe("Lapsed");
    expect(view.host.textContent).not.toContain("rm -rf");
    await view.done();
  });

  it("leaves out the time when the tap has none", async () => {
    const view = await mount(<ChatApproval a={{ ...card, status: "approved", decided_at: null }} />);
    expect(view.host.textContent).toBe("✓You allowed");
    await view.done();
  });

  it("keeps a pending card whole: its command and its buttons", async () => {
    const view = await mount(<ChatApproval a={card} />);
    expect(view.host.textContent).toContain("rm -rf ~/old-notes");
    const buttons = [...view.host.querySelectorAll("button")].map((b) => b.textContent);
    expect(buttons).toContain("Run it");
    expect(buttons).toContain("Not now");
    await view.done();
  });

  it("in Smart, says this one always asks and offers no 30-minute pass", async () => {
    forgetMode();
    vi.mocked(getJSON).mockResolvedValue({ mode: "smart" });
    const view = await mount(<ChatApproval a={card} />);
    await act(async () => { await Promise.resolve(); });
    const buttons = [...view.host.querySelectorAll("button")].map((b) => b.textContent);
    expect(buttons).toContain("Run it");
    expect(buttons.some((b) => b?.includes("30 min"))).toBe(false);
    expect(view.host.textContent).toContain("Smart mode: this one always asks.");
    forgetMode();
    vi.mocked(getJSON).mockReset();
    await view.done();
  });

  it("in Careful, keeps the 30-minute pass and the usual line", async () => {
    forgetMode();
    vi.mocked(getJSON).mockResolvedValue({ mode: "careful" });
    const view = await mount(<ChatApproval a={card} />);
    await act(async () => { await Promise.resolve(); });
    const buttons = [...view.host.querySelectorAll("button")].map((b) => b.textContent);
    expect(buttons.some((b) => b?.includes("30 min"))).toBe(true);
    expect(view.host.textContent).toContain("always ask first");
    forgetMode();
    vi.mocked(getJSON).mockReset();
    await view.done();
  });

  it("turns into the stamp the moment its status flips", async () => {
    const view = await mount(<ChatApproval a={card} />);
    expect(view.host.querySelector("button")).not.toBeNull();
    await view.show(<ChatApproval a={{ ...card, status: "approved", decided_at: decidedAt }} />);
    expect(view.host.textContent).toBe("✓You allowed · 12:01");
    expect(view.host.querySelector("button")).toBeNull();
    await view.done();
  });
});

// Chat.tsx's own wiring in miniature: the message holds the approval, and onDecided updates it with `answered`.
function ChatSlot({ first }: { first: Approval }) {
  const [a, setA] = useState(first);
  return <ChatApproval a={a} onDecided={(_id, status, until) => setA((was) => answered(was, status, until))} />;
}

describe("the shell pass on a stamp", () => {
  const until = new Date(2026, 10, 5, 12, 31).toISOString();  // 12:31 in this computer's own time zone
  it("says until when commands run without asking", async () => {
    const view = await mount(<ChatApproval a={{ ...card, status: "approved", decided_at: decidedAt, allowed_until: until }} />);
    expect(view.host.textContent).toContain("You allowed · 12:01 · commands run without asking until ");
    expect(view.host.textContent).toMatch(/until 12:31|until 0?12:31/);
    await view.done();
  });
  it("is not said on a refused card, even if a pass came along", async () => {
    const view = await mount(<ChatApproval a={{ ...card, status: "rejected", decided_at: decidedAt, allowed_until: until }} />);
    expect(view.host.textContent).toBe("✕You said no · 12:01");
    await view.done();
  });
  it("survives the live flip: tapping 'allow commands for 30 min' leaves a stamp that keeps the note", async () => {
    vi.mocked(postJSON).mockResolvedValueOnce({ status: "approved", allowed_until: until });
    const view = await mount(<ChatSlot first={card} />);
    const pass = [...view.host.querySelectorAll("button")].find((b) => b.textContent?.includes("allow commands for 30 min"));
    await act(async () => { pass!.click(); });
    expect(view.host.querySelector("button")).toBeNull();
    expect(view.host.textContent).toContain("You allowed");
    expect(view.host.textContent).toContain("commands run without asking until");
    await view.done();
  });
});

describe("answered", () => {
  it("stamps a live answer with the moment it was heard, and keeps the server's own time", () => {
    const flipped = answered(card, "approved");
    expect(flipped.status).toBe("approved");
    expect(Number.isNaN(new Date(flipped.decided_at ?? "").getTime())).toBe(false);
    expect(answered({ ...card, status: "approved", decided_at: decidedAt }, "approved").decided_at).toBe(decidedAt);
  });
  it("keeps the pass the tap granted", () => {
    expect(answered(card, "approved", "2026-11-05T12:31:00Z").allowed_until).toBe("2026-11-05T12:31:00Z");
    expect(answered({ ...card, allowed_until: "x" }, "approved").allowed_until).toBe("x");
  });
  it("changes nothing when there is no new status", () => {
    expect(answered(card, undefined)).toBe(card);
    expect(answered(card, "pending")).toBe(card);
  });
});
