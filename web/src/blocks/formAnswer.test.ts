// What a sent form becomes: the line the bubble shows, the block the model reads by field id, and when Send is allowed.
import { describe, expect, it } from "vitest";
import { readBlocks } from "./parse";
import type { FormBlock } from "./parse/form";
import { answerMessage, canSend, humanLine, readFormAnswers, startingValues, withoutFormAnswers } from "./formAnswer";

function form(raw: object): FormBlock {
  return readBlocks(JSON.stringify([{ type: "form", ...raw }]))!.blocks[0] as FormBlock;
}

const cast = form({
  id: "cast-lighthouse", title: "Cast the story",
  fields: [
    { id: "narrator", kind: "select", label: "Narrator", group: "Cast", value: "Fairy Godmother", options: ["Fairy Godmother", "Master Aldric"] },
    { id: "keeper", kind: "select", label: "The keeper", group: "Cast", value: "Old Mortlake", options: ["Old Mortlake", "Sir Bramwell"] },
    { id: "mira", kind: "select", label: "Mira", group: "Cast", value: "Maeve", options: ["Maeve", "Pippa"] },
    { id: "length", kind: "radio", label: "Length", value: "3 min", options: ["1 min", "3 min", "5 min"] },
    { id: "extras", kind: "checkbox", label: "Add", value: ["Sea sounds", "Chime at the end"], options: ["Sea sounds", "Music", "Chime at the end"] },
    { id: "pace", kind: "slider", label: "Pace", min: 0, max: 100, step: 10, value: 40, unit: "%" },
    { id: "notes", kind: "text", label: "Anything else", value: "end on the storm passing" },
  ],
});

describe("a sent form", () => {
  it("reads as one line in the bubble, groups together, in field order", () => {
    expect(humanLine(cast, startingValues(cast))).toBe(
      "Cast: Narrator → Fairy Godmother, The keeper → Old Mortlake, Mira → Maeve · Length: 3 min · Add: Sea sounds, Chime at the end · " +
      "Pace: 40% · Anything else: end on the storm passing");
  });

  it("leaves out empty optional fields, and an option's label stands for its value", () => {
    const f = form({ id: "f", fields: [
      { id: "where", kind: "select", label: "Where", options: [{ value: "h", label: "Hills" }, { value: "b", label: "Beach" }], value: "b" },
      { id: "notes", kind: "text", label: "Notes" },
      { id: "add", kind: "checkbox", label: "Add", options: ["Music"] },
      { id: "when", kind: "radio", label: "When", options: ["Sat", "Sun"] },
    ] });
    expect(humanLine(f, startingValues(f))).toBe("Where: Beach");
    expect(humanLine(f, { ...startingValues(f), notes: "   " })).toBe("Where: Beach");
  });

  it("carries every value by field id in an odie-form-answer block after the line", () => {
    const message = answerMessage(cast, startingValues(cast));
    const [line, rest] = message.split("\n\n");
    expect(line).toBe(humanLine(cast, startingValues(cast)));
    expect(rest.startsWith("```odie-form-answer\n") && rest.endsWith("\n```")).toBe(true);
    expect(readFormAnswers(message)).toEqual([{ form: "cast-lighthouse", values: {
      narrator: "Fairy Godmother", keeper: "Old Mortlake", mira: "Maeve", length: "3 min", extras: ["Sea sounds", "Chime at the end"],
      pace: 40, notes: "end on the storm passing" } }]);
  });

  it("sends a blank field as blank: null for an unchosen dropdown, [] for no boxes, \"\" for no text", () => {
    const f = form({ id: "f", fields: [
      { id: "s", kind: "select", label: "S", options: ["a"] }, { id: "c", kind: "checkbox", label: "C", options: ["a"] },
      { id: "t", kind: "text", label: "T" }] });
    expect(readFormAnswers(answerMessage(f, startingValues(f)))[0].values).toEqual({ s: null, c: [], t: "" });
  });

  it("shows only the line in a bubble: the answer block is for the model", () => {
    const message = answerMessage(cast, startingValues(cast));
    expect(withoutFormAnswers(message)).toBe(humanLine(cast, startingValues(cast)));
    expect(withoutFormAnswers("Just words.")).toBe("Just words.");
    expect(readFormAnswers("Just words.")).toEqual([]);
    expect(readFormAnswers("x\n\n```odie-form-answer\nnot json\n```")).toEqual([]);
  });

  it("allows Send once, when every required field has a value and no reply is streaming", () => {
    const f = form({ id: "f", fields: [
      { id: "name", kind: "text", label: "Name", required: true }, { id: "pick", kind: "radio", label: "Pick", required: true, options: ["a", "b"] },
      { id: "add", kind: "checkbox", label: "Add", options: ["x"] }] });
    const start = startingValues(f);
    expect(canSend(f, start, false, false)).toBe(false);  // nothing filled yet
    expect(canSend(f, { ...start, name: "Asha" }, false, false)).toBe(false);  // the radio is still empty
    const filled = { ...start, name: "Asha", pick: "b" };
    expect(canSend(f, filled, false, false)).toBe(true);
    expect(canSend(f, filled, true, false)).toBe(false);  // a reply is streaming
    expect(canSend(f, filled, false, true)).toBe(false);  // already sent
    expect(canSend(f, { ...filled, name: "  " }, false, false)).toBe(false);  // spaces aren't a name
  });
});
