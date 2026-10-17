// @vitest-environment jsdom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { describe, expect, it, vi } from "vitest";
import { copyText } from "../copy";
import { YourMessage } from "./YourMessage";

vi.mock("../copy", () => ({ copyText: vi.fn(async () => true) }));
(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

async function draw(node: React.ReactNode) {
  const host = document.createElement("div");
  document.body.appendChild(host);
  const root = createRoot(host);
  await act(async () => root.render(node));
  return { host, done: () => act(() => root.unmount()) };
}

describe("your own message", () => {
  it("has a copy button that copies exactly what you typed", async () => {
    const text = "Remind Asha about the dentist\non Friday at 5";
    const { host, done } = await draw(<YourMessage text={text} />);
    expect(host.textContent).toContain("Remind Asha about the dentist");
    const button = host.querySelector<HTMLButtonElement>('button[aria-label="Copy message"]')!;
    expect(button).not.toBeNull();
    await act(async () => button.click());
    expect(copyText).toHaveBeenCalledWith(text);
    done();
  });

  it("shows no copy button for a photo sent without words", async () => {
    const { host, done } = await draw(<YourMessage text="" images={["abc123"]} />);
    expect(host.querySelector("img")).not.toBeNull();
    expect(host.querySelector('button[aria-label="Copy message"]')).toBeNull();
    done();
  });
});
