// The form block's reader: each field kind as a model writes it, the clamps, what is dropped and why, and the rules
// for prefilled values and the form's id.
import { describe, expect, it } from "vitest";
import { readBlocks } from "../parse";
import { formIdFrom, previewPath } from "./form";

function one(block: unknown) {
  return readBlocks(JSON.stringify([block]))!;
}

const castForm = {
  type: "form", id: "cast-lighthouse", title: "Cast the story", submit: "Send",
  fields: [
    { id: "narrator", kind: "select", label: "Narrator", value: "Fairy Godmother", group: "Cast",
      options: [{ value: "Fairy Godmother", label: "Fairy Godmother", note: "warm, unhurried", preview: "/api/voice/preview/phonon/Fairy%20Godmother" }, "Master Aldric"] },
    { id: "length", kind: "radio", label: "Length", value: "3 min", options: ["1 min", "3 min", "5 min"] },
    { id: "extras", kind: "checkbox", label: "Add", value: ["Sea sounds"], options: ["Sea sounds", "Music", "Chime at the end"] },
    { id: "pace", kind: "slider", label: "Pace", min: 0, max: 100, step: 10, value: 40, unit: "%", ends: ["slow", "quick"] },
    { id: "notes", kind: "text", label: "Anything else", placeholder: "e.g. end on the storm passing", required: false, multiline: false },
  ],
};

describe("form", () => {
  it("reads every field kind, with the model's values prefilled", () => {
    const r = one(castForm);
    expect(r.dropped).toEqual([]);
    expect(r.blocks).toEqual([{
      type: "form", id: "cast-lighthouse", title: "Cast the story", submit: "Send", path: "0",
      fields: [
        { id: "narrator", kind: "select", label: "Narrator", group: "Cast", required: false, value: "Fairy Godmother",
          options: [{ value: "Fairy Godmother", label: "Fairy Godmother", note: "warm, unhurried", preview: "/api/voice/preview/phonon/Fairy%20Godmother" },
                    { value: "Master Aldric", label: "Master Aldric" }] },
        { id: "length", kind: "radio", label: "Length", required: false, value: "3 min",
          options: [{ value: "1 min", label: "1 min" }, { value: "3 min", label: "3 min" }, { value: "5 min", label: "5 min" }] },
        { id: "extras", kind: "checkbox", label: "Add", required: false, value: ["Sea sounds"],
          options: [{ value: "Sea sounds", label: "Sea sounds" }, { value: "Music", label: "Music" }, { value: "Chime at the end", label: "Chime at the end" }] },
        { id: "pace", kind: "slider", label: "Pace", required: false, min: 0, max: 100, step: 10, value: 40, unit: "%", ends: ["slow", "quick"] },
        { id: "notes", kind: "text", label: "Anything else", required: false, placeholder: "e.g. end on the storm passing", multiline: false },
      ],
    }]);
  });

  it("takes the names models also use: type for kind, dropdown, checkboxes, textarea, range", () => {
    const r = one({ type: "form", title: "Quick", fields: [
      { id: "a", type: "dropdown", label: "A", options: ["x", "y"] },
      { id: "b", kind: "checkboxes", label: "B", options: ["x"], value: "x" },
      { id: "c", kind: "textarea", label: "C" },
      { id: "d", kind: "range", label: "D", min: 1, max: 5 },
    ] });
    const kinds = (r.blocks[0] as any).fields.map((f: any) => [f.kind, f.multiline ?? null]);
    expect(kinds).toEqual([["select", null], ["checkbox", null], ["text", true], ["slider", null]]);
    expect((r.blocks[0] as any).fields[1].value).toEqual(["x"]);  // a lone checkbox value becomes a list of one
  });

  it("ignores a prefilled value that isn't one of the options", () => {
    const r = one({ type: "form", id: "f", fields: [
      { id: "s", kind: "select", label: "S", value: "nope", options: ["a", "b"] },
      { id: "r", kind: "radio", label: "R", value: "nope", options: ["a", "b"] },
      { id: "c", kind: "checkbox", label: "C", value: ["a", "nope"], options: ["a", "b"] },
    ] });
    const fields = (r.blocks[0] as any).fields;
    expect(fields[0].value).toBeUndefined();
    expect(fields[1].value).toBeUndefined();
    expect(fields[2].value).toEqual(["a"]);
  });

  it("keeps a slider's value in range and on its step; drops one whose min isn't below its max", () => {
    const r = one({ type: "form", id: "f", fields: [
      { id: "a", kind: "slider", label: "A", min: 0, max: 100, step: 10, value: 43 },
      { id: "b", kind: "slider", label: "B", min: 0, max: 1, step: 0.1, value: 7 },
      { id: "c", kind: "slider", label: "C", min: 5, max: 5 },
      { id: "d", kind: "slider", label: "D", min: 10, max: 20 },
    ] });
    const fields = (r.blocks[0] as any).fields;
    expect(fields.map((f: any) => [f.id, f.value])).toEqual([["a", 40], ["b", 1], ["d", 10]]);
    expect(r.dropped).toEqual([{ path: "0.fields.2", why: "slider needs min below max" }]);
  });

  it("drops a field with an unknown kind, no id or a repeated id, and says why", () => {
    const r = one({ type: "form", id: "f", fields: [
      { id: "a", kind: "date", label: "When" },
      { kind: "text", label: "No id" },
      { id: "b", kind: "text", label: "B" },
      { id: "b", kind: "text", label: "B again" },
      { id: "c", kind: "radio", label: "C", options: [] },
    ] });
    expect((r.blocks[0] as any).fields.map((f: any) => f.id)).toEqual(["b"]);
    expect(r.dropped).toEqual([
      { path: "0.fields.0", why: 'field kind "date" isn\'t one of select, radio, checkbox, text, slider' },
      { path: "0.fields.1", why: "field needs an id" },
      { path: "0.fields.3", why: 'field id "b" is used twice' },
      { path: "0.fields.4", why: "radio needs options" },
    ]);
  });

  it("isn't drawn at all without a usable field", () => {
    const r = one({ type: "form", id: "f", title: "Empty", fields: [{ id: "a", kind: "date" }] });
    expect(r.blocks).toEqual([]);
    expect(r.dropped.at(-1)).toEqual({ path: "0", why: "form has no usable field" });
    expect(one({ type: "form", title: "No list" }).blocks).toEqual([]);
  });

  it("clamps sizes: 12 fields, 60 options, labels, notes and a text value", () => {
    const many = Array.from({ length: 15 }, (_, i) => ({ id: `f${i}`, kind: "text", label: `Field ${i}` }));
    const r = one({ type: "form", id: "f", fields: many });
    expect((r.blocks[0] as any).fields.length).toBe(12);
    expect(r.dropped).toEqual([{ path: "0", why: "kept the first 12 fields of 15" }]);
    const options = Array.from({ length: 70 }, (_, i) => ({ value: `v${i}`, note: "n".repeat(100) }));
    const long = one({ type: "form", id: "f", fields: [
      { id: "s", kind: "select", label: "L".repeat(130), options },
      { id: "t", kind: "text", label: "T", value: "w".repeat(700) },
    ] });
    const [select, text] = (long.blocks[0] as any).fields;
    expect(select.options.length).toBe(60);
    expect(select.label.length).toBeLessThanOrEqual(100);
    expect(select.label.endsWith("…")).toBe(true);
    expect(select.options[0].note.length).toBe(80);
    expect(text.value.length).toBe(500);
  });

  it("keeps a preview only when it is one of Odie's own voice previews", () => {
    expect(previewPath("/api/voice/preview/phonon/Fairy%20Godmother")).toBe("/api/voice/preview/phonon/Fairy%20Godmother");
    expect(previewPath("/api/voice/preview/kokoro/af_heart")).toBe("/api/voice/preview/kokoro/af_heart");
    for (const bad of ["https://evil.example/a.mp3", "//evil.example/api/voice/preview/x", "/api/media/1", "/api/voice/preview/../../x",
                       "javascript:alert(1)", 42, undefined]) {
      expect(previewPath(bad), String(bad)).toBeUndefined();
    }
  });

  it("names a form from its title when it has no id, else form-1", () => {
    expect(formIdFrom(undefined, "Plan the weekend!")).toBe("plan-the-weekend");
    expect(formIdFrom("trip", "Plan the weekend")).toBe("trip");
    expect(formIdFrom(undefined, undefined)).toBe("form-1");
    expect(one({ type: "form", title: "Pick a pace", fields: [{ id: "p", kind: "radio", label: "P", options: ["a"] }] }).blocks[0])
      .toMatchObject({ id: "pick-a-pace", submit: "Send" });
  });

  it("reads required on any field", () => {
    const r = one({ type: "form", id: "f", fields: [{ id: "t", kind: "text", label: "Name", required: true }] });
    expect((r.blocks[0] as any).fields[0].required).toBe(true);
  });

  it("keeps a question-length label whole, and cuts a longer one at a word with …", () => {
    const asked = "Anything to slip in? (her pet's name, a favourite toy, a little lesson)";
    const tooLong = "What should the story be about, who is in it, where does it happen, and how should it end for her tonight?";
    const r = one({ type: "form", id: "f", fields: [{ id: "a", kind: "text", label: asked }, { id: "b", kind: "text", label: tooLong }] });
    const [a, b] = (r.blocks[0] as any).fields;
    expect(a.label).toBe(asked);
    expect(b.label).toBe("What should the story be about, who is in it, where does it happen, and how should it end for her…");
  });
});
