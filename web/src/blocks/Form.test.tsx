// @vitest-environment jsdom
// The form as drawn: Send only when it may be pressed, the message it sends, and the greyed answered state.
import { act } from "react";
import { createRoot } from "react-dom/client";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";
import { YourMessage } from "../components/YourMessage";
import { ChatActions } from "./ChatActions";
import { Form, FormView } from "./Form";
import { answerMessage, sentTime, startingValues } from "./formAnswer";
import { readBlocks } from "./parse";
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
