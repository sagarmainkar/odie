import { describe, expect, it } from "vitest";
import { canTurnOn, fromBeforeInput, fromKey, gesture, heldLabel, liveUrl, loginStatusText, offConfirm, sinceText, signedInLine, toPage, turnTitle, upiDetails, upiLink } from "./signin";

describe("the disclaimer", () => {
  it("turns on only with the box ticked, on the terms the server shows now", () => {
    expect(canTurnOn(false, 1, 1)).toBe(false);
    expect(canTurnOn(true, 1, 1)).toBe(true);
    expect(canTurnOn(true, 1, 2)).toBe(false);  // the terms changed while the sheet was open
    expect(canTurnOn(true, undefined, 1)).toBe(false);
  });

  it("says since when, in a few words", () => {
    expect(sinceText("2026-10-08T09:00:00+05:30", "en-IN")).toBe("8 Oct");
    expect(sinceText(null, "en-IN")).toBe("");
  });
});

describe("toPage", () => {
  const box = { left: 0, top: 50, width: 400, height: 800 };
  it("maps a tap on the shown frame to the page's CSS pixels", () => {
    // a 390 x 844 page fills the height: 800/844 scale, centred with side bars
    const s = 800 / 844, side = (400 - 390 * s) / 2;
    expect(toPage({ x: side + 195 * s, y: 50 + 422 * s }, box, { w: 390, h: 844 })).toEqual({ x: 195, y: 422 });
  });
  it("ignores the letterbox bars", () => {
    expect(toPage({ x: 2, y: 400 }, box, { w: 390, h: 844 })).toBeNull();
  });
  it("is the same whatever the image's own pixels (a 2x frame)", () => {
    expect(toPage({ x: 200, y: 50 + 400 }, { left: 0, top: 50, width: 400, height: 800 }, { w: 400, h: 800 })).toEqual({ x: 200, y: 400 });
  });
  it("keeps a drag that ends off the frame on its edge", () => {
    expect(toPage({ x: 200, y: 2000 }, { left: 0, top: 0, width: 400, height: 800 }, { w: 400, h: 800 }, true)).toEqual({ x: 200, y: 800 });
  });
  it("follows a zoomed frame (the box is the zoomed image's)", () => {
    expect(toPage({ x: 400, y: 850 }, { left: -200, top: -350, width: 800, height: 1600 }, { w: 400, h: 800 })).toEqual({ x: 300, y: 600 });
  });
});

describe("gesture", () => {
  it("is a tap unless the finger moved", () => {
    expect(gesture({ x: 10, y: 10 }, { x: 14, y: 13 })).toEqual({ t: "tap", x: 10, y: 10 });
    expect(gesture({ x: 100, y: 600 }, { x: 102, y: 200 })).toEqual({ t: "drag", x0: 100, y0: 600, x1: 102, y1: 200 });
  });
});

describe("keys", () => {
  it("sends typed text, and Backspace and Enter as keys", () => {
    expect(fromBeforeInput("insertText", "a")).toEqual({ t: "text", s: "a" });
    expect(fromBeforeInput("insertReplacementText", "hello")).toEqual({ t: "text", s: "hello" });
    expect(fromBeforeInput("deleteContentBackward", null)).toEqual({ t: "key", k: "Backspace" });
    expect(fromBeforeInput("insertLineBreak", null)).toEqual({ t: "key", k: "Enter" });
    expect(fromBeforeInput("insertParagraph", null)).toEqual({ t: "key", k: "Enter" });
    expect(fromBeforeInput("insertCompositionText", "ka")).toBeNull();  // the keyboard is still composing
    expect(fromBeforeInput("historyUndo", null)).toBeNull();
  });
  it("sends pasted and AutoFilled text, which comes with no data of its own", () => {
    expect(fromBeforeInput("insertFromPaste", null, "a-long-Passw0rd!")).toEqual({ t: "text", s: "a-long-Passw0rd!" });
    expect(fromBeforeInput("insertReplacementText", null, "asha@example.com")).toEqual({ t: "text", s: "asha@example.com" });
    expect(fromBeforeInput("insertFromPaste", null, null)).toBeNull();
  });
  it("takes Enter and Tab from keydown", () => {
    expect(fromKey("Enter")).toEqual({ t: "key", k: "Enter" });
    expect(fromKey("Tab")).toEqual({ t: "key", k: "Tab" });
    expect(fromKey("a")).toBeNull();
    expect(fromKey("Unidentified")).toBeNull();
  });
});

describe("links and lines", () => {
  it("turns an Android intent link into the UPI link it carries", () => {
    expect(upiLink("upi://pay?pa=a@ybl&am=1")).toBe("upi://pay?pa=a@ybl&am=1");
    expect(upiLink("intent://pay?pa=a@ybl&am=1#Intent;scheme=upi;package=x;end")).toBe("upi://pay?pa=a@ybl&am=1");
    expect(upiLink("intent://maps?q=x#Intent;scheme=geo;end")).toBeNull();
    expect(upiLink("javascript:alert(1)")).toBeNull();
  });
  it("reads who and how much from a UPI link", () => {
    expect(upiDetails("upi://pay?pa=shop@okaxis&pn=Shop%20One&am=499.00&tr=ORDER1")).toEqual({ payee: "Shop One", amount: "499.00" });
    expect(upiDetails("upi://pay?pa=shop@okaxis")).toEqual({ payee: "shop@okaxis", amount: "" });
    expect(upiDetails("not a link")).toEqual({ payee: "", amount: "" });
  });
  it("says what happened, in the chat", () => {
    expect(signedInLine("amazon.in", true)).toBe("I'm signed in to amazon.in.");
    expect(signedInLine("amazon.in", false)).toBe("I didn't sign in to amazon.in.");
  });
  it("opens the live view on the page's own host", () => {
    expect(liveUrl("chat-2026-10-08", { protocol: "https:", host: "odie.example:8443" })).toBe("wss://odie.example:8443/api/browser/live/chat-2026-10-08");
    expect(liveUrl("a b", { protocol: "http:", host: "localhost:8000" })).toBe("ws://localhost:8000/api/browser/live/a%20b");
  });
});

describe("held images", () => {
  it("names where a private reply's images would be fetched from", () => {
    expect(heldLabel(["https://www.evil.example/p.png?d=1"])).toBe("Show the image from evil.example");
    expect(heldLabel(["https://a.example/1.jpg", "https://a.example/2.jpg", "https://images.b.example/3.jpg"])).toBe("Show 3 images from a.example, images.b.example");
    expect(heldLabel(["https://a.example/1", "https://b.example/2", "https://c.example/3"])).toBe("Show 3 images from a.example, b.example and 1 more");
  });
});

describe("the sign-in box", () => {
  it("says what happened", () => {
    expect(loginStatusText("code", "amazon.in")).toBe("Enter the code amazon.in sent you.");
    expect(loginStatusText("failed", "amazon.in")).toBe("That didn't work: check the username and the password.");
    expect(loginStatusText("captcha", "amazon.in")).toBe("amazon.in wants a check only you can do.");
    expect(loginStatusText("wrong_site", "amazon.in")).toBe("The page isn't on amazon.in any more.");
    expect(loginStatusText("expired", "amazon.in")).toBe("That took too long: sign in again.");
    expect(loginStatusText("vault", "amazon.in")).toBe("Odie couldn't open its vault on the Mac.");
  });
  it("titles the card by its state", () => {
    expect(turnTitle(undefined, "amazon.in", false)).toBe("amazon.in needs you to sign in");
    expect(turnTitle("done", "amazon.in", true)).toBe("Signed in to amazon.in with your saved login");
    expect(turnTitle("done", "amazon.in", false)).toBe("Signed in to amazon.in");
    expect(turnTitle("failed", "amazon.in", true)).toBe("The saved password didn't work");
    expect(turnTitle("code", "amazon.in", true)).toBe("amazon.in sent you a code");
    expect(turnTitle("captcha", "amazon.in", true)).toBe("amazon.in wants a check only you can do");
    expect(turnTitle("vault", "amazon.in", true)).toBe("Odie couldn't open its vault on the Mac");
  });
  it("says what turning off forgets", () => {
    expect(offConfirm(0)).toBe("Turn off signed-in browsing? Odie signs out of every site first.");
    expect(offConfirm(1)).toBe("Turn off signed-in browsing? Odie signs out of every site and forgets 1 saved login.");
    expect(offConfirm(3)).toBe("Turn off signed-in browsing? Odie signs out of every site and forgets 3 saved logins.");
  });
});
