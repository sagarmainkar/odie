// @vitest-environment jsdom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { describe, expect, it } from "vitest";
import { answered } from "../approvals";
import { ChatApproval, type Approval } from "./ApprovalCard";

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

  it("turns into the stamp the moment its status flips", async () => {
    const view = await mount(<ChatApproval a={card} />);
    expect(view.host.querySelector("button")).not.toBeNull();
    await view.show(<ChatApproval a={{ ...card, status: "approved", decided_at: decidedAt }} />);
    expect(view.host.textContent).toBe("✓You allowed · 12:01");
    expect(view.host.querySelector("button")).toBeNull();
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
  it("changes nothing when there is no new status", () => {
    expect(answered(card, undefined)).toBe(card);
    expect(answered(card, "pending")).toBe(card);
  });
});
