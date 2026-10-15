import { describe, expect, it } from "vitest";
import { parseSseLines } from "./sse";

describe("parseSseLines", () => {
  it("splits complete events and keeps the remainder", () => {
    const { events, rest } = parseSseLines('data: {"type":"token","text":"a"}\n\ndata: {"type":"do');
    expect(events).toEqual([{ type: "token", text: "a" }]);
    expect(rest).toBe('data: {"type":"do');
  });
  it("ignores comments and blank lines", () => {
    expect(parseSseLines(": ping\n\n\n").events).toEqual([]);
  });
});

describe("parseSseLines with CRLF (sse-starlette default)", () => {
  it("parses events separated by \\r\\n\\r\\n", () => {
    const { events, rest } = parseSseLines('data: {"type":"token","text":"a"}\r\n\r\n: ping\r\n\r\ndata: {"type":"done","text":"a"}\r\n\r\n');
    expect(events).toEqual([{ type: "token", text: "a" }, { type: "done", text: "a" }]);
    expect(rest).toBe("");
  });
});
