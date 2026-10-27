// @vitest-environment jsdom
// The form as drawn: Send only when it may be pressed, the message it sends, and the greyed answered state.
import { act } from "react";
import { createRoot } from "react-dom/client";
import { renderToStaticMarkup } from "react-dom/server";
import { afterEach, describe, expect, it, vi } from "vitest";
import { YourMessage } from "../components/YourMessage";
import { ChatActions } from "./ChatActions";
import { Form, FormView } from "./Form";
import { answerMessage, sentTime, startingValues } from "./formAnswer";
import { readBlocks } from "./parse";
import { FencePlace, ReplyPlace } from "./SavedPlace";
import type { FormBlock } from "./parse/form";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

function form(raw: object): FormBlock {
  return readBlocks(JSON.stringify([{ type: "form", ...raw }]))!.blocks[0] as FormBlock;
}

const trip = form({ id: "trip", title: "Weekend", fields: [
  { id: "where", kind: "select", label: "Where", value: "Hills", options: [{ value: "Hills", note: "cool mornings" }, "Beach"] },
  { id: "pace", kind: "radio", label: "Pace", value: "Easy", options: ["Easy", "Packed"] },
  { id: "add", kind: "checkbox", label: "Add", value: ["Music"], options: ["Music", "Food stops"] },
  { id: "spend", kind: "slider", label: "Budget", min: 5, max: 30, step: 1, value: 12, unit: "k", ends: ["thrifty", "splurge"] },
  { id: "name", kind: "text", label: "Who's coming", required: true, placeholder: "e.g. Asha" },
] });

function mount(block: FormBlock, busy = false) {
  const send = vi.fn();
  const host = document.createElement("div");
  document.body.appendChild(host);
  const root = createRoot(host);
  act(() => root.render(<ChatActions.Provider value={{ send, fill: () => {}, busy }}><Form {...block} /></ChatActions.Provider>));
  return { host, send, sendButton: () => host.querySelector("button[type=submit]") as HTMLButtonElement };
}

function type(input: HTMLInputElement, text: string) {
  const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!;
  act(() => { setter.call(input, text); input.dispatchEvent(new Event("input", { bubbles: true })); });
}

describe("the form, drawn", () => {
  it("draws each kind: a dropdown, pills for radio and checkboxes, a slider with its ends, a text box", () => {
    const html = renderToStaticMarkup(<FormView form={trip} values={startingValues(trip)} sent={null} ready={false} onChange={() => {}} onSend={() => {}} />);
    expect(html).toContain("<select");
    expect(html).toContain("cool mornings");  // the chosen option's note
    expect(html).toMatch(/role="radio" aria-checked="true"[^>]*>.*Easy/);
    expect(html).toMatch(/role="checkbox" aria-checked="true"[^>]*>.*Music/);
    expect(html).toContain('type="range"');
    expect(html).toContain("thrifty");
    expect(html).toContain("splurge");
    expect(html).toContain('placeholder="e.g. Asha"');
    expect(html).toMatch(/<button type="submit"[^>]*disabled=""[^>]*>Send<\/button>/);
  });

  it("keeps Send disabled until the required text is filled, then sends the line and the answer", () => {
    const { host, send, sendButton } = mount(trip);
    expect(sendButton().disabled).toBe(true);
    type(host.querySelector("input[placeholder='e.g. Asha']") as HTMLInputElement, "Asha");
    expect(sendButton().disabled).toBe(false);
    act(() => sendButton().click());
    expect(send).toHaveBeenCalledTimes(1);
    expect(send).toHaveBeenCalledWith(answerMessage(trip, { ...startingValues(trip), name: "Asha" }));
    expect(send.mock.calls[0][0].startsWith("Where: Hills · Pace: Easy · Add: Music · Budget: 12 k · Who's coming: Asha")).toBe(true);
  });

  it("turns grey once sent, keeps the choices showing, says when, and can't be sent again", () => {
    const { host, send, sendButton } = mount(trip);
    type(host.querySelector("input[placeholder='e.g. Asha']") as HTMLInputElement, "Asha");
    act(() => sendButton().click());
    expect(host.querySelector("fieldset")!.disabled).toBe(true);
    expect(host.textContent).toMatch(/✓ Sent \d\d:\d\d/);
    expect((host.querySelector("input[placeholder='e.g. Asha']") as HTMLInputElement).value).toBe("Asha");
    expect(sendButton().disabled).toBe(true);
    act(() => sendButton().click());
    expect(send).toHaveBeenCalledTimes(1);
  });

  it("keeps Send disabled while a reply is streaming", () => {
    const ready = form({ id: "f", fields: [{ id: "p", kind: "radio", label: "P", value: "a", options: ["a"] }] });
    expect(mount(ready, true).sendButton().disabled).toBe(true);
    expect(mount(ready, false).sendButton().disabled).toBe(false);
  });

  it("writes the time it was sent as HH:MM", () => {
    expect(sentTime(new Date(2026, 9, 26, 15, 42).getTime())).toBe("15:42");
    expect(sentTime(new Date(2026, 9, 26, 9, 5).getTime())).toBe("09:05");
  });
});

describe("your message", () => {
  it("shows only the line of a form answer, and copies only that", () => {
    const message = answerMessage(trip, { ...startingValues(trip), name: "Asha" });
    const html = renderToStaticMarkup(<YourMessage text={message} />);
    expect(html).toContain("Where: Hills · Pace: Easy");
    expect(html).not.toContain("odie-form-answer");
    expect(html).not.toContain("&quot;form&quot;");
  });
});

describe("the form after a reload", () => {
  const REPLY = { sessionId: "chat-2026-10-26", messageKey: "3f2b9c1e-5d4a-4c8e-9a51-0b7d2e6f1a90" };
  const filled = { ...startingValues(trip), name: "Asha", where: "Beach" };

  async function mountInReply(saved: Record<string, unknown>, answers?: Record<string, Record<string, unknown>>) {
    const calls: { method: string; body?: any }[] = [];
    vi.stubGlobal("fetch", vi.fn(async (_url: string, init?: RequestInit) => {
      calls.push({ method: init?.method ?? "GET", body: init?.body ? JSON.parse(String(init.body)) : undefined });
      return new Response(JSON.stringify({ values: saved }), { status: 200 });
    }));
    const send = vi.fn();
    const host = document.createElement("div");
    document.body.appendChild(host);
    const root = createRoot(host);
    await act(async () => {
      root.render(
        <ChatActions.Provider value={{ send, fill: () => {}, busy: false }}>
          <ReplyPlace.Provider value={{ ...REPLY, text: "", answers: answers as any }}>
            <FencePlace.Provider value={{ reply: REPLY, fence: 0 }}><Form {...trip} /></FencePlace.Provider>
          </ReplyPlace.Provider>
        </ChatActions.Provider>);
    });
    await act(async () => { await new Promise((r) => setTimeout(r, 0)); });
    const nameBox = () => host.querySelector("input[placeholder='e.g. Asha']") as HTMLInputElement;
    return { host, send, calls, nameBox, sendButton: () => host.querySelector("button[type=submit]") as HTMLButtonElement };
  }

  afterEach(() => vi.unstubAllGlobals());

  it("draws a saved answer greyed, with its values and the time it was sent", async () => {
    const at = new Date(2026, 9, 26, 15, 42).getTime();
    const { host, nameBox, sendButton } = await mountInReply({ "0/0": { sent_at: new Date(at).toISOString(), values: filled } });
    expect(host.querySelector("fieldset")!.disabled).toBe(true);
    expect(nameBox().value).toBe("Asha");
    expect((host.querySelector("select") as HTMLSelectElement).value).toBe("Beach");
    expect(host.textContent).toContain("✓ Sent 15:42");
    expect(sendButton().disabled).toBe(true);
  });

  it("with nothing saved, takes an answer a later message carries, and draws it greyed", async () => {
    const { host, nameBox } = await mountInReply({}, { trip: { at: Date.parse("2026-10-26T10:12:00Z"), values: filled } });
    expect(host.querySelector("fieldset")!.disabled).toBe(true);
    expect(nameBox().value).toBe("Asha");
    expect(host.textContent).toMatch(/✓ Sent \d/);  // with the later message's time
  });

  it("with neither, is a live form; Send saves the answer with the reply", async () => {
    const { host, nameBox, sendButton, calls, send } = await mountInReply({});
    expect(host.querySelector("fieldset")!.disabled).toBe(false);
    expect(host.textContent).not.toContain("✓ Sent");
    type(nameBox(), "Asha");
    await act(async () => { sendButton().click(); await new Promise((r) => setTimeout(r, 0)); });
    expect(send).toHaveBeenCalledTimes(1);
    const put = calls.find((c) => c.method === "PUT")!;
    expect(put.body.block_path).toBe("0/0");
    expect(put.body.value.values).toEqual({ ...startingValues(trip), name: "Asha" });
    expect(typeof put.body.value.sent_at).toBe("string");
  });
});

describe("a voice the model left without its preview", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("gets its ▶ once Odie says which voices the chosen engine has", async () => {
    const answer = { engine: "phonon", engines: [{ id: "phonon", voices: [{ id: "Old Mortlake", label: "Old Mortlake" }] }] };
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify(answer), { status: 200 })));
    const { resetVoiceList } = await import("./voicePreviews");
    resetVoiceList();
    const cast = form({ id: "cast", fields: [{ id: "keeper", kind: "select", label: "Keeper", value: "Old Mortlake", options: ["Old Mortlake", "Hugh"] }] });
    const { host } = mount(cast);
    await act(async () => { await new Promise((done) => setTimeout(done, 0)); });
    expect(host.querySelector("button[aria-label='Hear Old Mortlake']")).not.toBeNull();
  });
});

