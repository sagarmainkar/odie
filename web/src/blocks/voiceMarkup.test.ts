import { describe, expect, it } from "vitest";
import { copyText } from "../copy";
import { drawnText } from "./drawnText";
import { couldBeMarker, hideVoiceMarkup } from "./voiceMarkup";

describe("hideVoiceMarkup", () => {
  it("takes out the tone marker and sound tags with the spaces before them", () => {
    expect(hideVoiceMarkup("<tone:wry>You paid twice? <laugh> No harm.")).toBe("You paid twice? No harm.");
    expect(hideVoiceMarkup("Oh <laugh>, fine.")).toBe("Oh, fine.");
    expect(hideVoiceMarkup("<sigh> Long day. <short pause> Rest now.")).toBe(" Long day. Rest now.");
  });

  it("reads markers in any case", () => {
    expect(hideVoiceMarkup("<TONE:Calm>Breathe <Sigh>.")).toBe("Breathe.");
  });

  it("leaves everything else alone", () => {
    const html = "a <b>bold</b> move, x < 5 and <tone:grumpy> stays";
    expect(hideVoiceMarkup(html)).toBe(html);
    const code = "```py\nif a:\n    print(1)\n```";
    expect(hideVoiceMarkup(code)).toBe(code);
  });

  it("holds back a marker still on its way while streaming", () => {
    expect(hideVoiceMarkup("<to")).toBe("");
    expect(hideVoiceMarkup("Hello <la")).toBe("Hello ");
    expect(hideVoiceMarkup("x < 5")).toBe("x < 5");
  });
});

describe("couldBeMarker", () => {
  it("knows the start of a marker", () => {
    expect(couldBeMarker("<tone:w")).toBe(true);
    expect(couldBeMarker("<long p")).toBe(true);
    expect(couldBeMarker("<div")).toBe(false);
    expect(couldBeMarker("< 5")).toBe(false);
  });
});

describe("where it applies", () => {
  it("the chat never draws the markup", () => {
    expect(drawnText("<tone:cheerful>Done! <chuckle> All paid.")).toBe("Done! All paid.");
  });

  it("copying a reply leaves the markup behind", async () => {
    let copied = "";
    const clipboard = { writeText: async (text: string) => { copied = text; } };
    await copyText("<tone:warm>See you soon. <laugh>", { clipboard });
    expect(copied).toBe("See you soon.");
  });
});
